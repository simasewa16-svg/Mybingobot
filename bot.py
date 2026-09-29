import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# የቦት ቶከንዎን ከአካባቢው ያነባል (በ Secrets ወይም Environment Variables ውስጥ ስላለ እዚህ ማስገባት አያስፈልግም)
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ሰላም! እንኳን ወደ ቢንጎ ቦት በደህና መጡ።\n"
        "ለመጫወት /bingo ብለው ይጻፉ።"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "የሚገኙ ትዕዛዞች:\n"
        "/start - ቦቱን ለመጀመር\n"
        "/bingo - አዲስ የቢንጎ ካርድ ለማግኘት\n"
        "/help - እርዳታ ለማግኘት"
    )

async def bingo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # የቢንጎ ቁጥሮችን በዘፈቀደ ማመንጨት
    b = random.sample(range(1, 16), 5)   # B: 1-15
    i = random.sample(range(16, 31), 5)  # I: 16-30
    n = random.sample(range(31, 46), 5)  # N: 31-45
    g = random.sample(range(46, 61), 5)  # G: 46-60
    o = random.sample(range(61, 76), 5)  # O: 61-75

    # መሃሉ ሁልጊዜ ነጻ (FREE) ይሆናል
    n[2] = "FREE"

    card = "🎲 **የእርስዎ የቢንጎ ካርድ** 🎲\n\n"
    card += "` B    I    N    G    O `\n"
    card += "------------------------\n"
    for row in range(5):
        card += f"`{b[row]:2}   {i[row]:2}   {n[row]:4}   {g[row]:2}   {o[row]:2}`\n"
    
    await update.message.reply_text(card, parse_mode='Markdown')

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(update.message.text)

# ለRender/Koyeb የሚያስፈልገው የድረ-ገጽ ሰርቨር (Port Binding)
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
    # የድረ-ገጽ ሰርቨሩን ከቦቱ ጋር በአንድ ጊዜ ማስነሳት
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    application = ApplicationBuilder().token(TOKEN).build()
    
    # ትዕዛዞችን ማገናኘት
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('bingo', bingo))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), echo))
    
    print("ቦቱ መስራት ጀምሯል...")
    application.run_polling()
