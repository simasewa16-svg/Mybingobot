import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ሰላም! እንኳን ደህና መጡ።\n"
        "/bingo - ካርድ ለማውጣት\n"
        "/call - አንድ ቁጥር ለመጥራት\n"
        "/start_game - ጨዋታ ለመጀመር (በየ5 ሰከንዱ ይጠራል)\n"
        "/stop - ጨዋታውን ለማቆም"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("የሚገኙ ትዕዛዞች:\n/start\n/bingo\n/call\n/start_game\n/stop")

async def bingo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    b = random.sample(range(1, 16), 5)
    i = random.sample(range(16, 31), 5)
    n = random.sample(range(31, 46), 5)
    g = random.sample(range(46, 61), 5)
    o = random.sample(range(61, 76), 5)
    n[2] = "FREE"
    card = "🎲 **የእርስዎ የቢንጎ ካርድ** 🎲\n\n"
    card += "` B    I    N    G    O `\n"
    card += "------------------------\n"
    for row in range(5):
        card += f"`{b[row]:2}   {i[row]:2}   {n[row]:4}   {g[row]:2}   {o[row]:2}`\n"
    await update.message.reply_text(card, parse_mode='Markdown')

# አንድ ቁጥር ብቻ መጥራት
async def call_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    num = random.randint(1, 75)
    if num <= 15: call = f"B-{num}"
    elif num <= 30: call = f"I-{num}"
    elif num <= 45: call = f"N-{num}"
    elif num <= 60: call = f"G-{num}"
    else: call = f"O-{num}"
    await update.message.reply_text(f"📢 የተጠራው ቁጥር: *{call}*", parse_mode='Markdown')

# በየ5 ሰከንዱ ቁጥር የሚጠራ ስራ (Auto Caller)
async def auto_call(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    num = random.randint(1, 75)
    if num <= 15: call = f"B-{num}"
    elif num <= 30: call = f"I-{num}"
    elif num <= 45: call = f"N-{num}"
    elif num <= 60: call = f"G-{num}"
    else: call = f"O-{num}"
    await context.bot.send_message(job.chat_id, text=f"📢 የተጠራው ቁጥር: *{call}*", parse_mode='Markdown')
    
    # ቁጥሮቹን መቁጠር (ከ10 ቁጥሮች በኋላ ያቆማል)
    job.data['count'] -= 1
    if job.data['count'] <= 0:
        job.schedule_removal()
        await context.bot.send_message(job.chat_id, text="✅ ጨዋታው አለቀ! (10 ቁጥሮች ተጠርተዋል)")

# ጨዋታውን መጀመር
async def start_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_message.chat_id
    if context.job_queue.get_jobs_by_name(str(chat_id)):
        await update.message.reply_text("⚠️ ጨዋታ አስቀድሞ ተጀምሯል! ለማቆም /stop ይጻፉ።")
        return
    context.job_queue.run_repeating(auto_call, interval=5, first=1, chat_id=chat_id, name=str(chat_id), data={'count': 10})
    await update.message.reply_text("🎲 ጨዋታ ተጀመረ! በየ5 ሰከንዱ አንድ ቁጥር ይጠራል (ጠቅላላ 10 ጊዜ)።\n/stop በማለት ማቆም ይችላሉ።")

# ጨዋታውን ማቆም
async def stop_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_message.chat_id
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    if not current_jobs:
        await update.message.reply_text("ምንም እየሰራ የለም!")
        return
    for job in current_jobs:
        job.schedule_removal()
    await update.message.reply_text("🛑 ጨዋታው ቆመ!")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text)

# ለRender የሚያስፈልገው የድረ-ገጽ ሰርቨር
def run_dummy_server():
    port = int(os.environ.get("PORT", 8000))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running!")
    server = HTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()

if __name__ == '__main__':
    threading.Thread(target=run_dummy_server, daemon=True).start()
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('bingo', bingo))
    application.add_handler(CommandHandler('call', call_number))
    application.add_handler(CommandHandler('start_game', start_auto))
    application.add_handler(CommandHandler('stop', stop_auto))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))
    
    print("ቦቱ መስራት ጀምሯል...")
    application.run_polling()
