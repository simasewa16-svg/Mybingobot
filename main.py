from fastapi import Request
import telebot

@app.post("/webhook/{token}")
async def webhook_handler(token: str, request: Request):
    if token != os.environ.get("BOT_TOKEN", ""):
        return {"ok": False}
    data = await request.json()
    update = telebot.types.Update.de_json(data)
    bot.process_new_updates([update])
    return {"ok": True}
