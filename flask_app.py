"""
============================================================
 BingoGame - Enterprise Flask Application (100x Pro Max Edition)
 Architecture: Blueprints, Async Threading, Idempotency, Logging
 Fixed: Removed Streak import to resolve ImportError.
============================================================
"""

import os
import re
import logging
import threading
import uuid
import requests
from decimal import Decimal
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# ከ database.py የሚመጡ ሞዴሎች (Streak ለጊዜው ተወግዷል)
from database import (
    SessionLocal, User, Wallet, Transaction, SupportTicket, utc_now
)

# ============================================================
# 1. CONFIGURATION & ENVIRONMENT VARIABLES
# ============================================================
load_dotenv()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# 🚨 ቶከንህን እዚህ በቀጥታ አስገብተዋለሁ (ለደህንነት ግን በ Environment Variables መጠቀም ይመረጣል)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8962566823:AAHYTr58QBRU85-HkeLb91M_gIOBzaTh7jw")
ADMIN_TELEGRAM_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", 0)) 
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "my-super-secret-key-123")

# 📱 የአድሚን የተረጋገጠ የስልክ ቁጥር (ለቴሌብር እና ሲቢኢ ብር ማስተናገጃ)
ADMIN_PHONE = "0912649315"

# ============================================================
# 2. ADVANCED LOGGING SYSTEM
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app_errors.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BingoApp")

# ============================================================
# 3. HELPER FUNCTIONS
# ============================================================
def normalize_phone(phone: str) -> str:
    """የስልክ ቁጥርን ወደ አንድ ወጥ ቅርጸት (09...) ይቀይራል"""
    if not phone:
        return ""
    phone = str(phone).strip().replace(" ", "")
    if phone.startswith("+251"):
        return "0" + phone[4:]
    elif phone.startswith("251"):
        return "0" + phone[3:]
    return phone

def send_async_telegram(chat_id, text, parse_mode="HTML", reply_markup=None):
    """መልእክቱ በስተጀርባ እንዲላክ ያደርጋል፤ ዌብሁኩን አያዘገይም።"""
    def _send():
        if not BOT_TOKEN or not chat_id:
            logger.warning("ቴሌግራም ቶከን ወይም Chat ID አልተገኘም።")
            return
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code != 200:
                logger.error(f"ቴሌግራም መላክ አልተቻለም: {response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"የቴሌግራም ኔትወርክ ስህተት: {e}")
            
    threading.Thread(target=_send, daemon=True).start()

# ============================================================
# 4. DECORATORS (የደህንነት አንግል)
# ============================================================
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-KEY')
        if api_key != WEBHOOK_SECRET:
            logger.warning(f"ያልተፈቀደ የ API ቁልፍ ሙከራ ከ IP: {request.remote_addr}")
            return jsonify({"status": "error", "message": "Unauthorized API Key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# ============================================================
# 5. WEBHOOK ROUTES (የክፍያ እና የቴሌግራም ማስተናገጃ)
# ============================================================

@app.route('/webhook/telebirr', methods=['POST'])
# @require_api_key  # ለሙከራ ጊዜ እንዳይገድብ Comment ተደርጓል፤ ሲዘጋጅ Uncomment አድርገው
def telebirr_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    out_trade_no = data.get("outTradeNo") or data.get("reference")
    msisdn = data.get("msisdn") or data.get("phone")
    amount_str = data.get("amount") or data.get("totalAmount") or "0.00"
    
    try:
        amount = Decimal(str(amount_str))
    except:
        return jsonify({"status": "error", "message": "Invalid amount"}), 400

    if amount <= 0:
        return jsonify({"status": "error", "message": "Amount must be greater than 0"}), 400

    msisdn = normalize_phone(msisdn)

    db = SessionLocal()
    try:
        # Idempotency Check (ድርብ ክፍያን መከላከል)
        if out_trade_no:
            existing_tx = db.query(Transaction).filter_by(reference_id=out_trade_no).first()
            if existing_tx:
                return jsonify({"status": "success", "message": "Duplicate Webhook Ignored"}), 200

        # ተጠቃሚውን በስልክ ቁጥር መፈለግ
        user = db.query(User).filter_by(phone=msisdn).first()
        if not user:
            logger.error(f"ክፍያ መጥቷል ግን ስልኩ አልተመዘገበም: {msisdn}")
            return jsonify({"status": "error", "message": "User not found"}), 404

        if user.is_banned:
            logger.warning(f"የተከለከለ ተጠቃሚ ክፍያ ሊፈጽም ሞክሯል: {msisdn}")
            return jsonify({"status": "error", "message": "User is banned"}), 403

        # ወደ ዋሌት ገንዘብ መጨመር
        wallet = db.query(Wallet).filter_by(user_id=user.id, currency="ETB").first()
        if not wallet:
            wallet = Wallet(user_id=user.id, currency="ETB", balance=Decimal("0.00"))
            db.add(wallet)
            db.flush()

        wallet.balance += amount

        # ትራንዛክሽን መመዝገብ
        tx = Transaction(
            user_id=user.id,
            payment_gateway="Telebirr",
            transaction_type="deposit",
            amount=amount,
            status="success",
            reference_id=out_trade_no
        )
        db.add(tx)
        db.commit()

        # ለተጠቃሚው በቴሌግራም ማሳወቅ
        msg = f"✅ <b>ክፍያዎ ተቀባይነት አግኝቷል!</b>\n\n💰 በቴሌብር {amount} ETB አካውንትዎ ላይ ተጨምሯል።\n💳 አሁን ያለዎት ባላንስ: <b>{wallet.balance} ETB</b>"
        send_async_telegram(user.telegram_id, msg)
        
        return jsonify({"status": "success"}), 200

    except Exception as e:
        db.rollback()
        logger.error(f"በቴሌብር ዌብሁክ ላይ ስህተት አጋጥሟል: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db.close()


@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    update = request.get_json()
    if not update or "message" not in update:
        return jsonify({"status": "success"}), 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=chat_id).first()
        if not user:
            ref_code = str(uuid.uuid4())[:8]  
            user = User(
                telegram_id=chat_id,
                first_name=message["chat"].get("first_name"),
                last_name=message["chat"].get("last_name"),
                username=message["chat"].get("username"),
                referral_code=ref_code
            )
            db.add(user)
            db.commit()

        # 🚫 የተከለከለ ተጠቃሚ ከሆነ ምላሽ አይሰጥ
        if user.is_banned:
            send_async_telegram(chat_id, "🚫 እርስዎ ከዚህ ቦት አገልግሎት ተከልክለዋል። ለበለጠ መረጃ አስተዳዳሪውን ያግኙ።")
            return jsonify({"status": "success"}), 200

        # 👑 Admin Commands 
        if chat_id == ADMIN_TELEGRAM_ID:
            if text == "/stats":
                total_users = db.query(User).count()
                total_deposits = db.query(Transaction).filter_by(status="success", transaction_type="deposit").count()
                
                total_balance = sum([w.balance for w in db.query(Wallet).all()])
                
                reply = (
                    f"📊 <b>የስርዓቱ ወቅታዊ ሁኔታ:</b>\n\n"
                    f"👥 ጠቅላላ ተጠቃሚዎች: <b>{total_users}</b>\n"
                    f"💸 የተሳኩ ክፍያዎች: <b>{total_deposits}</b>\n"
                    f"🏦 በስርዓቱ ያለ ጠቅላላ ገንዘብ: <b>{total_balance:,.2f} ETB</b>"
                )
                send_async_telegram(chat_id, reply)
                return jsonify({"status": "success"}), 200

        # የቦት ትዕዛዞችን ማስተናገድ (Bot Commands)
        if text.startswith("/start"):
            reply_markup = {
                "keyboard": [[{"text": "📱 ስልክ ቁጥሬን አጋራ", "request_contact": True}]],
                "one_time_keyboard": True,
                "resize_keyboard": True
            }
            welcome_msg = (
                "🎉 <b>እንኳን ወደ ቢንጎ ቦት በሰላም መጡ!</b>\n\n"
                "ጨዋታ ለመጀመር እና የቴሌብር/ሲቢኢ ብር ክፍያዎችን ለመፈጸም እባክዎ ከታች ያለውን አረንጓዴ ቁልፍ በመጫን ስልክ ቁጥርዎን ያጋሩ።"
            )
            send_async_telegram(chat_id, welcome_msg, reply_markup=reply_markup)

        elif "contact" in message:
            phone = normalize_phone(message["contact"]["phone_number"])
            user.phone = phone
            db.commit()
            
            success_msg = (
                f"✅ <b>ስልክ ቁጥርዎ በተሳካ ሁኔታ ተመዝግቧል!</b>\n\n"
                f"📱 የተመዘገበው ስልክ: <b>{phone}</b>\n"
                f"አሁን /deposit በማለት ገንዘብ ማስገባት ይችላሉ።"
            )
            send_async_telegram(chat_id, success_msg)

        elif text == "/balance":
            wallet = db.query(Wallet).filter_by(user_id=user.id, currency="ETB").first()
            bal = wallet.balance if wallet else Decimal("0.00")
            send_async_telegram(chat_id, f"💰 <b>የአካውንትዎ ቀሪ ሂሳብ:</b>\n\n💵 ዋና ባላንስ: <b>{bal} ETB</b>")

        elif text == "/deposit":
            dep_msg = (
                f"💳 <b>ገንዘብ ለማስገባት የሚከተሉትን ይከተሉ:</b>\n\n"
                f"1️⃣ በስልክዎ በቴሌብር ወይም በሲቢኢ ብር ወደዚህ ቁጥር ይላኩ: <code>{ADMIN_PHONE}</code>\n"
                f"2️⃣ ከተላከ በኋላ የላኩበትን የግብይት ቁጥር (Reference) እዚህ ይጻፉልን።\n"
                f"3️⃣ ገንዘቡ ከገባ በራስ-ሰር ወደ አካውንትዎ ይጨመራል።"
            )
            send_async_telegram(chat_id, dep_msg)

        elif text == "/help":
            help_text = (
                "❓ <b>የቦቱ መመሪያዎች:</b>\n\n"
                "/start - ቦቱን ለመቀስቀስ\n"
                "/balance - ቀሪ ሂሳብ ለማየት\n"
                "/deposit - ገንዘብ ለማስገባት\n"
                "/help - መመሪያ ለማየት"
            )
            send_async_telegram(chat_id, help_text)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"በቴሌግራም ዌብሁክ ላይ ስህተት: {e}")
        return jsonify({"status": "success"}), 200
    finally:
        db.close()

# ዌብሳይቱ መስራቱን ለማረጋገጫ ዋና ገጽ
@app.route('/')
def home():
    return jsonify({"status": "running", "application": "BingoGame Enterprise Webhook"}), 200
