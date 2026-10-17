"""
=====================================================================
✅ የBingo ጨዋታ ጀርባ ስርዓት (main.py) - v9.3 WEBHOOK READY
=====================================================================
"""

from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect, func
from sqlalchemy.exc import IntegrityError, OperationalError, DBAPIError, InterfaceError
from pydantic import BaseModel, Field
from decimal import Decimal, ROUND_DOWN
from typing import Literal, List, Optional
import os
import uuid
import secrets
import telebot
from telebot import types
import threading
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# ✅ Safe escape_markdown import
try:
    from telebot.formatting import escape_markdown
except ImportError:
    def escape_markdown(text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        escape_chars = r'\_*[]()~`>#+-=|{}.!'
        return ''.join('\\' + c if c in escape_chars else c for c in text)

from database import engine, get_db, Base, SessionLocal
from auth import verify_telegram_init_data
from admin_auth import (
    get_admin_user, has_permission, is_super_admin, require_permission,
    log_admin_action, ALL_PERMISSIONS, ROLE_PERMISSIONS, get_admin_permissions,
)
import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

secure_random = secrets.SystemRandom()
_feedback_rate_limit = defaultdict(list)

# ✅ Settings Cache
_settings_cache = {}
_settings_cache_time = 0
SETTINGS_CACHE_TTL = 60

app = FastAPI(title="Bingo Game API")

# =====================================================================
# ✅ የአካባቢ ቅንብሮች
# =====================================================================
ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
ALLOWED_ORIGINS_ENV = os.getenv("ALLOWED_ORIGINS", "")
BOT_POLLING_ENABLED = os.getenv("BOT_POLLING_ENABLED", "false").lower() == "true"

if ENVIRONMENT == "production":
    allowed_origins = [o.strip() for o in ALLOWED_ORIGINS_ENV.split(",") if o.strip()]
    if not allowed_origins:
        allowed_origins = ["https://web.telegram.org", "https://t.me"]
else:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "HEAD", "DELETE"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

# =====================================================================
# ✅ DB Error Handler Middleware
# =====================================================================
@app.middleware("http")
async def db_error_handler(request: Request, call_next):
    try:
        return await call_next(request)
    except HTTPException:
        raise
    except (OperationalError, DBAPIError, InterfaceError) as e:
        logger.error(f"❌ DB Error in {request.url.path}: {e}")
        return JSONResponse(status_code=503, content={"detail": "ዳታቤዙ ግንኙነት ተቋርጧል"})
    except Exception as e:
        logger.exception(f"❌ Unhandled error in {request.url.path}: {e}")
        return JSONResponse(status_code=500, content={"detail": f"የውስጥ ስህተት: {str(e)[:150]}"})

# ✅ BOT_TOKEN ማስተካከያ (ሁለቱንም ይቀበላል)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN", "")
SUPER_ADMIN_ID = os.getenv("ADMIN_ID", "")
SUPER_ADMIN_USERNAME = os.getenv("SUPER_ADMIN_USERNAME", "Super Admin")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://bingobot2026.pythonanywhere.com")

try:
    SUPER_ADMIN_CHAT_ID = int(SUPER_ADMIN_ID) if SUPER_ADMIN_ID else None
except (ValueError, TypeError):
    SUPER_ADMIN_CHAT_ID = None

# =====================================================================
# ✅ ቋሚ እሴቶች
# =====================================================================
ENGINE_LOCK_ID = 987654321
GAME_CREATE_LOCK_ID = 987654322
BOT_POLLING_LOCK_ID = 987654323
WAITING_TIMEOUT_MINUTES = 30
DRAW_INTERVAL_SECONDS = 5
MAX_NUMBERS = 75
MIN_DEPOSIT = 10
MAX_DEPOSIT = 50000
MIN_WITHDRAWAL = Decimal("50.00")
MAX_WITHDRAWAL = Decimal("50000.00")
MIN_CARDS_TO_START = 2

# =====================================================================
# ✅ Telegram Bot
# =====================================================================
bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        try:
            markup = types.InlineKeyboardMarkup()
            web_app = types.WebAppInfo(url=WEBAPP_URL)
            btn = types.InlineKeyboardButton("🎮 ጨዋታውን ክፈት", web_app=web_app)
            markup.add(btn)
            bot.reply_to(message, "ሰላም! የቢንጎ ጨዋታ ቦት እንኳን ደህና መጣህ/ሽ! 🎉", reply_markup=markup)
        except Exception as e:
            logger.error(f"send_welcome error: {e}")
            bot.reply_to(message, "ሰላም! እባክዎ እንደገና ይሞክሩ።")

# =====================================================================
# ✅ WEBHOOK ENDPOINT (ለPythonAnywhere ወሳኝ)
# =====================================================================
@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != BOT_TOKEN:
        return {"ok": False, "error": "Invalid token"}
    try:
        json_data = await request.json()
        update = telebot.types.Update.de_json(json_data)
        bot.process_new_updates([update])
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        return {"ok": False, "error": str(e)}

def cleanup_feedback_limits():
    while True:
        try:
            time.sleep(3600)
            now = time.time()
            dead_users = []
            for user_id, timestamps in list(_feedback_rate_limit.items()):
                timestamps[:] = [t for t in timestamps if now - t < 60]
                if not timestamps:
                    dead_users.append(user_id)
            for user_id in dead_users:
                del _feedback_rate_limit[user_id]
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# =====================================================================
# ✅ Settings Helpers
# =====================================================================
def get_setting(db: Session, key: str, default=None):
    global _settings_cache, _settings_cache_time
    now = time.time()
    if now - _settings_cache_time > SETTINGS_CACHE_TTL:
        try:
            settings = db.query(models.Setting).all()
            _settings_cache = {s.key: (s.value, s.value_type) for s in settings}
            _settings_cache_time = now
        except Exception as e:
            logger.error(f"Settings cache error: {e}")
    if key in _settings_cache:
        value, vtype = _settings_cache[key]
        try:
            if vtype == "int": return int(value)
            elif vtype == "decimal": return Decimal(value)
            elif vtype == "bool": return value.lower() == "true"
            else: return value
        except (ValueError, TypeError): return default
    return default

def set_setting(db: Session, key: str, value, value_type: str, admin_id: str = None):
    global _settings_cache, _settings_cache_time
    setting = db.query(models.Setting).filter(models.Setting.key == key).first()
    if setting:
        setting.value = str(value)
        setting.value_type = value_type
        setting.updated_at = datetime.now(timezone.utc)
        setting.updated_by = admin_id
    else:
        setting = models.Setting(key=key, value=str(value), value_type=value_type, updated_at=datetime.now(timezone.utc), updated_by=admin_id)
        db.add(setting)
    _settings_cache[key] = (str(value), value_type)
    _settings_cache_time = time.time()
    return setting

def ensure_default_settings(db: Session):
    defaults = [
        ("card_price", "10", "decimal", "የካርድ ዋጋ (ብር)"),
        ("min_cards_to_start", "2", "int", "ዝቅተኛ ካርድ ቁጥር"),
        ("draw_interval_seconds", "5", "int", "የጥሪ ክፍተት (ሰከንድ)"),
        ("jackpot_percent", "100", "int", "የጃክፖት %"),
        ("min_deposit", "10", "int", "ዝቅተኛ Deposit (ብር)"),
        ("min_withdrawal", "50", "int", "ዝቅተኛ Withdrawal (ብር)"),
    ]
    for key, value, vtype, desc in defaults:
        existing = db.query(models.Setting).filter(models.Setting.key == key).first()
        if not existing:
            db.add(models.Setting(key=key, value=value, value_type=vtype, description=desc, updated_by="system"))
    db.commit()

# =====================================================================
# ✅ Helper ተግባሮች
# =====================================================================
def ensure_super_admin_exists(db: Session):
    if not SUPER_ADMIN_ID: return None
    admin = db.query(models.AdminUser).filter(models.AdminUser.telegram_id == SUPER_ADMIN_ID).first()
    if not admin:
        admin = models.AdminUser(telegram_id=SUPER_ADMIN_ID, display_name=SUPER_ADMIN_USERNAME, role="super_admin", is_active=True)
        db.add(admin)
        db.commit()
        db.refresh(admin)
    return admin

def add_ledger(db, user, entry_type, amount, ref_type=None, ref_id=None, notes=None):
    entry = models.LedgerEntry(user_id=user.id, entry_type=entry_type, amount=amount, balance_after=user.balance, reference_type=ref_type if ref_type else "system", reference_id=str(ref_id) if ref_id is not None else "auto", notes=notes)
    db.add(entry)
    return entry

def lock_user(db, user_id):
    return db.query(models.User).filter(models.User.id == user_id).with_for_update().first()

def lock_game(db, game_id):
    return db.query(models.Game).filter(models.Game.id == game_id).with_for_update().first()

def safe_db_execute(db: Session, retries: int = 20):
    for attempt in range(retries):
        try:
            db.execute(text("SELECT 1"))
            return True
        except (OperationalError, DBAPIError, InterfaceError):
            try: db.rollback()
            except Exception: pass
            if attempt < retries - 1: time.sleep(5)
    return False

# =====================================================================
# ✅ Bingo Card Validation
# =====================================================================
def validate_bingo_card(nums: List[int]) -> tuple:
    if not isinstance(nums, list) or len(nums) != 25: return (False, "invalid_length")
    if nums[12] != 0: return (False, "center_not_free")
    column_ranges = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75)]
    for r in range(5):
        for c in range(5):
            i = r * 5 + c
            if i == 12: continue
            n = nums[i]
            if type(n) is not int: return (False, f"non_integer_at_{i}")
            if n == 0: return (False, f"zero_at_{i}")
            low, high = column_ranges[c]
            if not (low <= n <= high): return (False, f"out_of_range_at_{i}")
    non_zero = [n for i, n in enumerate(nums) if i != 12]
    if len(non_zero) != len(set(non_zero)): return (False, "duplicate_numbers")
    return (True, None)

def check_card_winner(nums: List[int], called_set: set) -> bool:
    is_valid, _ = validate_bingo_card(nums)
    if not is_valid: return False
    grid = [nums[i * 5:(i + 1) * 5] for i in range(5)]
    grid[2][2] = 0
    if any(all(grid[r][c] == 0 or grid[r][c] in called_set for c in range(5)) for r in range(5)): return True
    if any(all(grid[r][c] == 0 or grid[r][c] in called_set for r in range(5)) for c in range(5)): return True
    if all(grid[i][i] == 0 or grid[i][i] in called_set for i in range(5)): return True
    if all(grid[i][4 - i] == 0 or grid[i][4 - i] in called_set for i in range(5)): return True
    return False

def parse_called_numbers(called_str: Optional[str]) -> Optional[set]:
    if called_str is None or called_str.strip() == "": return set()
    parts = called_str.split(",")
    called = set()
    try:
        for part in parts:
            part = part.strip()
            if not part: return None
            n = int(part)
            if str(n) != part: return None
            if not 1 <= n <= MAX_NUMBERS: return None
            if n in called: return None
            called.add(n)
    except (ValueError, TypeError): return None
    return called

# =====================================================================
# ✅ Authentication
# =====================================================================
async def get_current_user(x_telegram_init_data: str = Header(None), db: Session = Depends(get_db)):
    if not BOT_TOKEN: raise HTTPException(status_code=503, detail="የቦት ቶከን አልተዋቀረም")
    if not x_telegram_init_data: raise HTTPException(status_code=401, detail="የማንነት ማረጋገጫ የለም")
    tg_user = verify_telegram_init_data(x_telegram_init_data, BOT_TOKEN)
    if not tg_user: raise HTTPException(status_code=401, detail="የተሳሳተ ማረጋገጫ")
    tg_id = str(tg_user.get("id"))
    user = db.query(models.User).filter(models.User.telegram_id == tg_id).first()
    if not user:
        try:
            user = models.User(telegram_id=tg_id, username=tg_user.get("username"), first_name=tg_user.get("first_name"), last_name=tg_user.get("last_name"), balance=Decimal("0.00"))
            db.add(user)
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            user = db.query(models.User).filter(models.User.telegram_id == tg_id).first()
            if not user: raise HTTPException(status_code=500, detail="የተጠቃሚ ፍጠራ ስህተት")
    if user.is_banned: raise HTTPException(status_code=403, detail="አካውንትዎ ታግዷል")
    try:
        user.last_active = datetime.now(timezone.utc)
        db.commit()
    except Exception: db.rollback()
    return user

async def require_admin(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin = get_admin_user(db, user.telegram_id)
    if not admin and user.telegram_id == SUPER_ADMIN_ID:
        ensure_super_admin_exists(db)
        admin = get_admin_user(db, user.telegram_id)
    if not admin: raise HTTPException(status_code=403, detail="የAdmin ፈቃድ የለዎትም")
    try:
        admin.last_login = datetime.now(timezone.utc)
        db.commit()
    except Exception: db.rollback()
    return admin

# =====================================================================
# ✅ Request Models
# =====================================================================
class DepositRequest(BaseModel):
    amount: Decimal = Field(..., ge=MIN_DEPOSIT, le=MAX_DEPOSIT, max_digits=12, decimal_places=2)
    method: Literal["ቴሌብር", "ሲቢኢ ብር"]
    reference: str = Field(..., min_length=1, max_length=100)

class BuyCardRequest(BaseModel):
    game_id: int = Field(..., gt=0)

class WithdrawalRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    method: Literal["ቴሌብር", "ሲቢኢ ብር"]
    account_number: str = Field(..., min_length=5, max_length=100)
    account_name: Optional[str] = Field(None, max_length=255)

class ApproveWithdrawalRequest(BaseModel):
    reference: str = Field(..., min_length=1, max_length=100)
    notes: Optional[str] = None

class CreateAdminRequest(BaseModel):
    telegram_id: str = Field(..., min_length=5, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., pattern="^(sub_admin|finance_admin|moderator|viewer)$")
    notes: Optional[str] = None

class AdjustBalanceRequest(BaseModel):
    amount: Decimal = Field(..., max_digits=12, decimal_places=2)
    reason: str = Field(..., min_length=3, max_length=200)

class AddPlayerNoteRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=1000)
    is_warning: bool = False

class FeedbackRequest(BaseModel):
    message: str = Field(..., min_length=3, max_length=1000)
    category: Literal["አስተያየት", "ችግር", "ጥያቄ", "ሀሳብ"] = "አስተያየት"

class UpdateSettingsRequest(BaseModel):
    card_price: Optional[Decimal] = Field(None, ge=1, le=1000)
    min_cards_to_start: Optional[int] = Field(None, ge=2, le=10)
    draw_interval_seconds: Optional[int] = Field(None, ge=3, le=10)
    jackpot_percent: Optional[int] = Field(None, ge=80, le=100)
    min_deposit: Optional[int] = Field(None, ge=1, le=1000)
    min_withdrawal: Optional[int] = Field(None, ge=10, le=10000)

# =====================================================================
# ✅ Game Cancellation Helper
# =====================================================================
def _cancel_game_with_refund(db, game_id: int):
    game = lock_game(db, game_id)
    if not game or game.refunded: return (0, True)
    cards = db.query(models.Card).filter(models.Card.game_id == game_id, models.Card.refunded == False).with_for_update().all()
    refunded_count = 0
    for card in cards:
        existing_refund = db.query(models.LedgerEntry).filter(models.LedgerEntry.user_id == card.user_id, models.LedgerEntry.entry_type == "refund", models.LedgerEntry.reference_type == "card", models.LedgerEntry.reference_id == str(card.id)).first()
        if existing_refund: continue
        nested = db.begin_nested()
        try:
            user = lock_user(db, card.user_id)
            if not user: nested.rollback(); continue
            user.balance = Decimal(str(user.balance)) + card.price_paid
            add_ledger(db, user, "refund", card.price_paid, ref_type="card", ref_id=card.id, notes=f"ጨዋታ #{game_id} ሰረዘ")
            nested.commit()
            card.refunded = True
            card.refunded_at = datetime.now(timezone.utc)
            refunded_count += 1
        except Exception as e:
            nested.rollback()
            logger.error(f"Refund error card {card.id}: {e}")
    total_cards = db.query(models.Card).filter(models.Card.game_id == game_id).count()
    refunded_total = db.query(models.Card).filter(models.Card.game_id == game_id, models.Card.refunded == True).count()
    is_complete = (total_cards == 0) or (refunded_total == total_cards)
    if is_complete:
        game.refunded = True
        game.status = "cancelled"
        game.finished_at = datetime.now(timezone.utc)
    return (refunded_count, is_complete)

# =====================================================================
# ✅ BASIC ROUTES
# =====================================================================
@app.get("/")
def read_root():
    try: return FileResponse("templates/index.html")
    except Exception: return JSONResponse(status_code=404, content={"detail": "Page not found"})

@app.get("/api/status")
def api_status(): return {"message": "የቢንጎ ጨዋታ ጀርባ ስርዓት እየሰራ ነው!"}

@app.api_route("/api/health", methods=["GET", "HEAD"])
def health_check():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})

# =====================================================================
# ✅ GAME ENDPOINTS
# =====================================================================
@app.get("/api/game/current/state")
def get_or_create_current_game(db: Session = Depends(get_db)):
    if not safe_db_execute(db, retries=15): raise HTTPException(status_code=503, detail="ዳታቤዙ ግንኙነት ተቋርጧል")
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": GAME_CREATE_LOCK_ID})
        game = db.query(models.Game).filter(models.Game.status.in_(["waiting", "playing"])).order_by(models.Game.id.desc()).first()
        if game and game.status == "waiting" and game.created_at:
            if datetime.now(timezone.utc) - game.created_at > timedelta(minutes=WAITING_TIMEOUT_MINUTES):
                _, is_complete = _cancel_game_with_refund(db, game.id)
                if not is_complete: raise HTTPException(status_code=503, detail="የቀድሞ ጨዋታ ገንዘብ መመለስ አልተሟላም።")
                game = None
        if not game:
            prev_game = db.query(models.Game).filter(models.Game.rollover_jackpot > 0, models.Game.status == "finished").order_by(models.Game.id.desc()).with_for_update().first()
            initial_jackpot = Decimal("0.00")
            rollover_received = Decimal("0.00")
            if prev_game and prev_game.rollover_jackpot > 0:
                initial_jackpot = prev_game.rollover_jackpot
                rollover_received = prev_game.rollover_jackpot
                prev_game.rollover_jackpot = Decimal("0.00")
                prev_game.rollover_transferred = True
            card_price = get_setting(db, "card_price", Decimal("10.00"))
            game = models.Game(status="waiting", jackpot=initial_jackpot, original_jackpot=initial_jackpot, rollover_received=rollover_received, card_price=card_price)
            db.add(game)
            db.commit()
            db.refresh(game)
        player_count = db.query(models.Card).filter(models.Card.game_id == game.id).count()
        return {"id": game.id, "status": game.status, "jackpot": float(game.jackpot or 0), "card_price": float(game.card_price or 10), "call_count": game.call_count, "called_numbers": game.called_numbers or "", "last_number": game.last_number, "players_count": player_count}
    except HTTPException: raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="ዳታቤዙ ግንኙነት ተቋርጧል")

@app.get("/api/game/{game_id}")
def get_game_state(game_id: int, db: Session = Depends(get_db)):
    game = db.query(models.Game).filter(models.Game.id == game_id).first()
    if not game: return {"error": "ጨዋታው አልተገኘም"}
    player_count = db.query(models.Card).filter(models.Card.game_id == game_id).count()
    return {"id": game.id, "status": game.status, "jackpot": float(game.jackpot or 0), "card_price": float(game.card_price or 10), "call_count": game.call_count, "called_numbers": game.called_numbers or "", "last_number": game.last_number, "players_count": player_count, "winner_id": game.winner_id}

@app.get("/api/me")
def get_me(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    admin = get_admin_user(db, user.telegram_id)
    return {"id": user.id, "telegram_id": user.telegram_id, "username": user.username, "first_name": user.first_name, "balance": float(user.balance), "is_admin": bool(admin), "is_super_admin": bool(admin and is_super_admin(admin))}

@app.get("/api/my_card/{game_id}")
def get_my_card(game_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    card = db.query(models.Card).filter(models.Card.user_id == user.id, models.Card.game_id == game_id).first()
    if not card: return {"has_card": False}
    return {"has_card": True, "card_id": card.id, "numbers": card.numbers, "is_winner": card.is_winner}

@app.post("/api/deposit")
def request_deposit(req: DepositRequest, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    clean_reference = req.reference.strip()
    if not clean_reference: raise HTTPException(status_code=422, detail="የደረሰኝ ቁጥሩ ባዶ መሆን የለበትም")
    new_trans = models.Transaction(user_id=user.id, amount=Decimal(str(req.amount)), method=req.method, reference=clean_reference, status="pending")
    db.add(new_trans)
    try:
        db.commit()
        db.refresh(new_trans)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="ይህ የደረሰኝ ቁጥር ተጠቅሟል!")
    return {"message": "የክፍያ ጥያቄዎ ተልኳል።", "transaction_id": new_trans.id}

@app.post("/api/buy_card")
def buy_card(req: BuyCardRequest, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    game = lock_game(db, req.game_id)
    if not game: raise HTTPException(status_code=404, detail="ጨዋታው አልተገኘም")
    if game.status != "waiting": raise HTTPException(status_code=400, detail="ጨዋታው ተጀምሯል ወይም ተጠናቋል")
    locked_user = lock_user(db, user.id)
    card_price = game.card_price or Decimal("10.00")
    if locked_user.balance < card_price: raise HTTPException(status_code=400, detail="በቂ ባላንስ የለዎትም")
    existing_card = db.query(models.Card).filter(models.Card.user_id == locked_user.id, models.Card.game_id == req.game_id).first()
    if existing_card: raise HTTPException(status_code=400, detail="በዚህ ጨዋታ ካርድ ገዝተዋል")
    columns = [secure_random.sample(range(1, 16), 5), secure_random.sample(range(16, 31), 5), secure_random.sample(range(31, 46), 5), secure_random.sample(range(46, 61), 5), secure_random.sample(range(61, 76), 5)]
    nums = [columns[c][r] for r in range(5) for c in range(5)]
    nums[12] = 0
    is_valid, err = validate_bingo_card(nums)
    if not is_valid: raise HTTPException(status_code=500, detail="የካርድ ፍጠራ ስህተት")
    card_numbers = ",".join(map(str, nums))
    nested = db.begin_nested()
    try:
        locked_user.balance = locked_user.balance - card_price
        new_card = models.Card(user_id=locked_user.id, game_id=req.game_id, numbers=card_numbers, price_paid=card_price)
        db.add(new_card)
        db.flush()
        add_ledger(db, locked_user, "card_purchase", -card_price, ref_type="card", ref_id=new_card.id, notes=f"ጨዋታ #{game.id}")
        nested.commit()
    except Exception as e:
        nested.rollback()
        raise HTTPException(status_code=500, detail="የውስጥ ስህተት")
    total_cards = db.query(models.Card).filter(models.Card.game_id == req.game_id).count()
    min_cards = get_setting(db, "min_cards_to_start", 2)
    game.jackpot = (game.jackpot or Decimal("0.00")) + card_price
    if total_cards >= min_cards and game.status == "waiting":
        game.status = "playing"
        game.started_at = datetime.now(timezone.utc)
        game.last_drawn_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "ካርድ ተገዝቷል!", "balance": float(locked_user.balance), "card": card_numbers}

@app.get("/api/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    try:
        results = db.query(models.User.id, models.User.telegram_id, models.User.username, models.User.first_name, func.coalesce(func.sum(models.LedgerEntry.amount), 0).label("total_won"), func.count(models.LedgerEntry.id).label("win_count")).join(models.LedgerEntry, models.LedgerEntry.user_id == models.User.id).filter(models.LedgerEntry.entry_type == "prize_payout").group_by(models.User.id, models.User.telegram_id, models.User.username, models.User.first_name).order_by(func.sum(models.LedgerEntry.amount).desc()).limit(20).all()
        leaderboard = []
        for i, r in enumerate(results, 1):
            name = r.username or r.first_name or f"User_{str(r.telegram_id)[-4:]}"
            leaderboard.append({"rank": i, "username": name, "total_won": float(r.total_won), "win_count": int(r.win_count)})
        return {"leaderboard": leaderboard}
    except Exception as e:
        return {"leaderboard": []}

@app.get("/api/history")
def get_history(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = db.query(models.LedgerEntry).filter(models.LedgerEntry.user_id == user.id).order_by(models.LedgerEntry.created_at.desc()).limit(50).all()
    return {"history": [{"id": e.id, "type": e.entry_type, "amount": float(e.amount), "balance_after": float(e.balance_after), "notes": e.notes or "", "created_at": e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else ""} for e in entries]}

@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest, user: models.User = Depends(get_current_user)):
    now = time.time()
    user_limits = _feedback_rate_limit[user.id]
    user_limits[:] = [t for t in user_limits if now - t < 60]
    if len(user_limits) >= 1: raise HTTPException(status_code=429, detail="እባክዎ 1 ደቂቃ ጠብቀው ይሞክሩ።")
    user_limits.append(now)
    try:
        if bot and SUPER_ADMIN_CHAT_ID:
            safe_name = escape_markdown(user.first_name or 'ያልታወቀ')
            safe_username = escape_markdown(user.username or 'N/A')
            safe_message = escape_markdown(req.message[:3800])
            text = f"📬 *አዲስ አስተያየት*\n\n👤 *ከ:* {safe_name} (@{safe_username})\n🆔 `{user.telegram_id}`\n📂 *ምድብ:* {req.category}\n\n💬 *መልእክት:*\n{safe_message}"
            try: bot.send_message(SUPER_ADMIN_CHAT_ID, text, parse_mode="Markdown")
            except Exception: bot.send_message(SUPER_ADMIN_CHAT_ID, text.replace("*", "").replace("`", "").replace("_", ""))
        return {"message": "አስተያየትዎ ደርሶናል!"}
    except Exception:
        raise HTTPException(status_code=500, detail="አስተያየት መላክ አልተቻለም")

@app.post("/api/withdrawal")
def request_withdrawal(req: WithdrawalRequest, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.amount < MIN_WITHDRAWAL: raise HTTPException(status_code=400, detail=f"ዝቅተኛ መጠን {MIN_WITHDRAWAL} ብር")
    if req.amount > MAX_WITHDRAWAL: raise HTTPException(status_code=400, detail=f"ከፍተኛ መጠን {MAX_WITHDRAWAL} ብር")
    locked_user = lock_user(db, user.id)
    if locked_user.balance < req.amount: raise HTTPException(status_code=400, detail="በቂ ባላንስ የለዎትም")
    locked_user.balance = locked_user.balance - req.amount
    withdrawal = models.Withdrawal(user_id=locked_user.id, amount=req.amount, method=req.method, account_number=req.account_number.strip(), account_name=req.account_name.strip() if req.account_name else None, status="pending")
    db.add(withdrawal)
    db.flush()
    add_ledger(db, locked_user, "withdrawal_pending", -req.amount, ref_type="withdrawal", ref_id=withdrawal.id, notes=f"ጥያቄ #{withdrawal.id}")
    db.commit()
    return {"message": "የማውጣት ጥያቄዎ ተልኳል", "withdrawal_id": withdrawal.id}

@app.get("/api/withdrawal/my")
def my_withdrawals(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    withdrawals = db.query(models.Withdrawal).filter(models.Withdrawal.user_id == user.id).order_by(models.Withdrawal.created_at.desc()).limit(50).all()
    return {"withdrawals": [{"id": w.id, "amount": float(w.amount), "method": w.method, "status": w.status, "reference": w.reference, "created_at": w.created_at.strftime("%Y-%m-%d %H:%M") if w.created_at else ""} for w in withdrawals]}

# =====================================================================
# ✅ ADMIN ENDPOINTS (አስተዳዳሪ ክፍል - ሙሉ ለማይሆን አስፈላጊው ብቻ)
# =====================================================================
@app.get("/api/admin/me")
def get_admin_info(admin: models.AdminUser = Depends(require_admin)):
    return {"id": admin.id, "telegram_id": admin.telegram_id, "display_name": admin.display_name, "role": admin.role, "is_super": is_super_admin(admin), "permissions": get_admin_permissions(admin), "all_permissions": ALL_PERMISSIONS}

@app.get("/api/admin/stats")
def get_admin_stats(admin: models.AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    require_permission(admin, "view_dashboard")
    return {
        "players": {"total": db.query(models.User).count(), "banned": db.query(models.User).filter(models.User.is_banned == True).count(), "flagged": db.query(models.User).filter(models.User.is_flagged == True).count()},
        "pending": {"deposits": db.query(models.Transaction).filter(models.Transaction.status == "pending").count(), "withdrawals": db.query(models.Withdrawal).filter(models.Withdrawal.status == "pending").count()},
        "money": {"total_deposited": float(db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(models.Transaction.status == "approved").scalar() or 0)},
        "games": {"total": db.query(models.Game).count(), "active": db.query(models.Game).filter(models.Game.status.in_(["waiting", "playing"])).count()}
    }

@app.get("/api/admin/pending")
def get_pending_deposits(admin: models.AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    require_permission(admin, "approve_deposits")
    pending = db.query(models.Transaction).filter(models.Transaction.status == "pending").order_by(models.Transaction.created_at.asc()).all()
    return {"pending": [{"id": t.id, "amount": float(t.amount), "method": t.method, "reference": t.reference, "created_at": t.created_at.strftime("%Y-%m-%d %H:%M")} for t in pending]}

@app.post("/api/admin/approve/{transaction_id}")
def approve_deposit(transaction_id: int, admin: models.AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    require_permission(admin, "approve_deposits")
    trans = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).with_for_update().first()
    if not trans or trans.status != "pending": raise HTTPException(status_code=400, detail="ልክ ያልሆነ ግብይት")
    user = lock_user(db, trans.user_id)
    if not user: raise HTTPException(status_code=404, detail="ተጠቃሚው አልተገኘም")
    user.balance = user.balance + trans.amount
    add_ledger(db, user, "deposit_approved", trans.amount, ref_type="transaction", ref_id=trans.id, notes=trans.method)
    trans.status = "approved"
    trans.reviewed_by = admin.telegram_id
    trans.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "ጸድቋል!", "new_balance": float(user.balance)}

@app.get("/api/admin/settings")
def get_settings_endpoint(admin: models.AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    settings = db.query(models.Setting).all()
    return {"settings": {s.key: s.value for s in settings}}

@app.put("/api/admin/settings")
def update_settings_endpoint(req: UpdateSettingsRequest, admin: models.AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    updates = req.dict(exclude_unset=True, exclude_none=True)
    changed = []
    for key, value in updates.items():
        existing = db.query(models.Setting).filter(models.Setting.key == key).first()
        if existing:
            set_setting(db, key, value, existing.value_type, admin.telegram_id)
            changed.append(key)
    db.commit()
    return {"message": "ቅንብሮች ተስተካክለዋል", "changed": changed}

# =====================================================================
# ✅ BINGO ENGINE LOOP
# =====================================================================
def bingo_engine_loop():
    while True:
        try:
            db_tmp = SessionLocal()
            try: draw_interval = get_setting(db_tmp, "draw_interval_seconds", 5)
            finally: db_tmp.close()
            time.sleep(draw_interval)
        except Exception: time.sleep(5); continue

        dedicated_conn = None
        got_lock = False
        try:
            try: dedicated_conn = engine.raw_connection()
            except Exception: continue
            cursor = dedicated_conn.cursor()
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (ENGINE_LOCK_ID,))
            got_lock = cursor.fetchone()[0]
            cursor.close()
            if not got_lock: continue
            db = SessionLocal()
            try:
                process_engine_tick(db)
                db.commit()
            except Exception as tick_error:
                db.rollback()
                logger.error(f"Engine tick error: {tick_error}")
            finally: db.close()
        except Exception as fatal_error:
            logger.error(f"Engine fatal error: {fatal_error}")
        finally:
            if dedicated_conn:
                try:
                    if got_lock:
                        cursor = dedicated_conn.cursor()
                        cursor.execute("SELECT pg_advisory_unlock(%s)", (ENGINE_LOCK_ID,))
                        dedicated_conn.commit()
                        cursor.close()
                except Exception: pass
                finally:
                    try: dedicated_conn.close()
                    except Exception: pass

def process_engine_tick(db):
    old_games = db.query(models.Game).filter(models.Game.status == "waiting").all()
    for og in old_games:
        if og.created_at and datetime.now(timezone.utc) - og.created_at > timedelta(minutes=WAITING_TIMEOUT_MINUTES):
            _cancel_game_with_refund(db, og.id)

    games = db.query(models.Game).filter(models.Game.status == "playing").with_for_update().all()
    for game in games:
        existing_payout = db.query(models.LedgerEntry.id).filter(models.LedgerEntry.entry_type == "prize_payout", models.LedgerEntry.reference_type == "game", models.LedgerEntry.reference_id == str(game.id)).first()
        if existing_payout and not game.payout_completed: continue
        draw_interval = get_setting(db, "draw_interval_seconds", 5)
        if game.last_drawn_at and (datetime.now(timezone.utc) - game.last_drawn_at).total_seconds() < draw_interval: continue
        called_set = parse_called_numbers(game.called_numbers)
        if called_set is None: continue
        called_list = sorted(called_set)
        if len(called_list) >= MAX_NUMBERS:
            _finish_game_no_winner(db, game); continue
        available = [n for n in range(1, MAX_NUMBERS + 1) if n not in called_set]
        if not available: _finish_game_no_winner(db, game); continue
        new_num = secure_random.choice(available)
        called_list.append(new_num)
        game.called_numbers = ",".join(str(x) for x in called_list)
        game.last_number = new_num
        game.call_count = len(called_list)
        game.last_drawn_at = datetime.now(timezone.utc)
        check_winners(db, game, set(called_list))

def _finish_game_no_winner(db, game):
    if game.payout_completed: return
    game.rollover_jackpot = (game.rollover_jackpot or Decimal("0.00")) + (game.jackpot or Decimal("0.00"))
    game.jackpot = Decimal("0.00")
    game.payout_completed = True
    game.status = "finished"
    game.finished_at = datetime.now(timezone.utc)

def check_winners(db, game, called_set):
    if game.payout_completed or game.status != "playing": return
    game = lock_game(db, game.id)
    if not game or game.payout_completed or game.status != "playing": return
    cards = db.query(models.Card).filter(models.Card.game_id == game.id, models.Card.refunded.is_(False)).order_by(models.Card.id.asc()).with_for_update().all()
    winners = []
    for card in cards:
        try: nums = [int(x) for x in card.numbers.split(",")]
        except Exception: continue
        if check_card_winner(nums, called_set): winners.append(card)
    if not winners: return
    jackpot = Decimal(str(game.jackpot or "0.00")).quantize(Decimal("0.01"))
    if jackpot <= Decimal("0.00"): return
    winners.sort(key=lambda c: c.id)
    n = len(winners)
    share = (jackpot / Decimal(n)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    remainder = jackpot - (share * n)
    for i, card in enumerate(winners):
        amount = share + (remainder if i == 0 else Decimal("0.00"))
        user = lock_user(db, card.user_id)
        if user:
            user.balance = Decimal(str(user.balance)) + amount
            add_ledger(db, user, "prize_payout", amount, ref_type="game", ref_id=game.id, notes=f"payout card {card.id}")
            card.is_winner = True
    game.winner_id = winners[0].user_id
    game.status = "finished"
    game.finished_at = datetime.now(timezone.utc)
    game.payout_completed = True
    game.jackpot = Decimal("0.00")

# =====================================================================
# ✅ STARTUP (ማስጀመሪያ - Webhook ስለሆነ run_bot አያስፈልግም)
# =====================================================================
@app.on_event("startup")
def startup_event():
    logger.info("⏳ ሰርቨሩ በመነሳት ላይ ነው...")
    try:
        db_init = SessionLocal()
        try: ensure_default_settings(db_init)
        finally: db_init.close()
    except Exception as e:
        logger.warning(f"⚠️ Settings init warning: {e}")

    # ✅ Bot Polling ተወግዷል! (Webhook ተጠቅመናል)
    
    threading.Thread(target=bingo_engine_loop, daemon=True).start()
    logger.info("✅ Bingo engine started.")
    threading.Thread(target=cleanup_feedback_limits, daemon=True).start()
    logger.info("✅ Bingo backend started successfully.")

# =====================================================================
# ✅ Dynamic Port
# =====================================================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
