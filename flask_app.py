from flask import Flask, request
import telebot
import os
from database import init_db

app = Flask(__name__)

# 1. ቦት ቶከን
BOT_TOKEN = os.getenv("BOT_TOKEN", "የአንተ_ቦት_ቶከን_እዚህ_ይገባል")
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# 2. ዳታቤዙን አንድ ጊዜ ፍጠር
init_db()

# 3. የአንተን main.py ሎጂክ እዚህ ጋር አስገባ (ወይም import አድርግ)
# ለምሳሌ: from main import register_all_handlers
# register_all_handlers(bot)
# (የ Bingo ጨዋታ ሎጂክህ እዚህ ወይም በ import ይገባል)

# 4. Webhook Route (PythonAnywhere ይህን ይቀበላል)
@app.route('/<token>', methods=['POST'])
def webhook(token):
    if token == BOT_TOKEN:
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '', 403

# 5. ሙከራ Route
@app.route('/')
def hello():
    return "Bingo Bot is running on PythonAnywhere!"
