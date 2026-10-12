from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
import telebot
import threading
import random

from database import engine, get_db, Base
import models

# የዳታቤዝ ሠንጠረዦችን መፍጠር
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Bingo Game API")

# የ CORS ፈቃድ (ለፊት ገጽታው እንዲገናኝ)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== የቴሌግራም ቦት ማዋቀር ====================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TOKEN_HERE")
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "ሰላም! የቢንጎ ጨዋታ ቦት እንኳን ደህና መጣህ/ሽ! ለመጫወት ከታች ያለውን ቁልፍ ተጭነው ይግቡ።")

def run_bot():
    bot.polling(none_stop=True)

# ==================== የ API መግለጫዎች (Models) ====================
class DepositRequest(BaseModel):
    user_id: str
    amount: float
    method: str
    reference: str

class BuyCardRequest(BaseModel):
    user_id: str
    game_id: int

# ==================== የ API አገልግሎቶች (Endpoints) ====================

@app.get("/")
def read_root():
    return {"message": "የቢንጎ ጨዋታ ጀርባ ስርዓት እየሰራ ነው!"}

# 1. የተጠቃሚ መረጃ ማግኘት
@app.get("/api/user/{telegram_id}")
def get_user(telegram_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.telegram_id == telegram_id).first()
    if not user:
        user = models.User(telegram_id=telegram_id, balance=0.0)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"id": user.id, "telegram_id": user.telegram_id, "balance": user.balance}

# 2. የክፍያ ጥያቄ መላክ (Manual Verification)
@app.post("/api/deposit")
def request_deposit(req: DepositRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.telegram_id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ተጠቃሚው አልተገኘም")
    
    # የደረሰኝ ቁጥሩ ደጋግሞ እንዳልተጠቀመበት ማረጋገጥ
    existing = db.query(models.Transaction).filter(models.Transaction.reference == req.reference).first()
    if existing:
        raise HTTPException(status_code=400, detail="ይህ የደረሰኝ ቁጥር ከዚህ በፊት ተጠቅሟል!")

    new_trans = models.Transaction(
        user_id=user.id,
        amount=req.amount,
        method=req.method,
        reference=req.reference,
        status="pending"
    )
    db.add(new_trans)
    db.commit()
    return {"message": "የክፍያ ጥያቄዎ በተሳካ ሁኔታ ተልኳል። አስተዳዳሪው ሲያረጋግጥ ባላንስዎ ይሞላል።"}

# 3. ካርድ መግዛት
@app.post("/api/buy_card")
def buy_card(req: BuyCardRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.telegram_id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ተጠቃሚው አልተገኘም")
    
    card_price = 10.0
    if user.balance < card_price:
        raise HTTPException(status_code=400, detail="በቂ ባላንስ የለዎትም። እባክዎ ገንዘብ ያስገቡ።")
    
    # ባላንስ መቀነስ
    user.balance -= card_price
    
    # የቢንጎ ካርድ ቁጥሮችን ማመንጨት (1-75)
    card_numbers = ",".join(str(random.randint(1, 75)) for _ in range(25))
    
    new_card = models.Card(user_id=user.id, game_id=req.game_id, numbers=card_numbers)
    db.add(new_card)
    db.commit()
    
    return {"message": "ካርድ በተሳካ ሁኔታ ገዝተዋል!", "new_balance": user.balance, "card": card_numbers}

# 4. የጨዋታ ሁኔታ ማግኘት (ለፊት ገጽታው)
@app.get("/api/game/{game_id}")
def get_game_state(game_id: int, db: Session = Depends(get_db)):
    game = db.query(models.Game).filter(models.Game.id == game_id).first()
    if not game:
        # አዲስ ጨዋታ መፍጠር (ለሙከራ)
        game = models.Game(status="waiting", jackpot=0.0)
        db.add(game)
        db.commit()
        db.refresh(game)
    
    return {
        "id": game.id,
        "status": game.status,
        "jackpot": game.jackpot,
        "call_count": game.call_count,
        "called_numbers": game.called_numbers
    }

# 5. የአስተዳዳሪ ማረጋገጫ (Deposit Approve)
@app.post("/api/admin/approve/{transaction_id}")
def approve_deposit(transaction_id: int, db: Session = Depends(get_db)):
    trans = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not trans:
        raise HTTPException(status_code=404, detail="ግብይቱ አልተገኘም")
    
    if trans.status == "approved":
        raise HTTPException(status_code=400, detail="ግብይቱ አስቀድሞ ተረጋግጧል")
    
    trans.status = "approved"
    user = db.query(models.User).filter(models.User.id == trans.user_id).first()
    user.balance += trans.amount
    db.commit()
    return {"message": "ግብይቱ በተሳካ ሁኔታ ጸድቋል!", "new_balance": user.balance}

# የቦቱን ስራ በተ parallel ማስኬድ
@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=run_bot)
    thread.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
