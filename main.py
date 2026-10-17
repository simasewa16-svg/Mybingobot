import os
import logging
import telebot
from fastapi import FastAPI, Request
from database import engine, Base

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

if not BOT_TOKEN:
    logger.warning("⚠️ BOT_TOKEN is missing in environment variables!")

# Telegram Bot Setup
bot = telebot.TeleBot(BOT_TOKEN)

# FastAPI Setup
app = FastAPI(title="BingoGame API")

# Create Database Tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables checked/created successfully.")
except Exception as e:
    logger.error(f"❌ Database initialization error: {e}")

# ==========================================
# 1. TELEGRAM BOT HANDLERS
# ==========================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """ተጠቃሚ /start ሲጫን የሚሰጥ ምላሽ"""
    welcome_text = (
        "🎉 እንኳን ደህና መጣህ/ሽ!\n\n"
        "ወደ BingoGame ቦት በደህና መጡ።\n"
        "ለመጫወት ከታች ያለውን ቁልፍ ተጫኑ።"
    )
    bot.reply_to(message, welcome_text)


@bot.message_handler(func=lambda message: True)
def echo_all(message):
    """ሌሎች መልእክቶች ሲመጡ የሚሰጥ ምላሽ"""
    bot.reply_to(message, "ይህን ትዕዛዝ አላወቅኩም። እባክህ /start ተጫን።")


# ==========================================
# 2. FASTAPI ROUTES (Webhook & Health)
# ==========================================

@app.get("/")
def read_root():
    """ሰርቨሩ መስራቱን ለማረጋገጥ"""
    return {"status": "ok", "message": "Bingo Backend is running!"}


@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    """ቴሌግራም መልእክቶችን የሚቀበልበት የWebhook መንገድ"""
    # ቶከኑ ትክክል መሆኑን ማረጋገጥ
    if token != BOT_TOKEN:
        return {"ok": False, "error": "Invalid token"}
    
    try:
        # የቴሌግራም ዳታ መቀበል እና ማካሄድ
        json_data = await request.json()
        update = telebot.types.Update.de_json(json_data)
        bot.process_new_updates([update])
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        return {"ok": False, "error": str(e)}
