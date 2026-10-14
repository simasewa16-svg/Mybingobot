"""
=====================================================================
✅ የBingo ጨዋታ ጀርባ ስርዓት (main.py) - v7.1 (Schema Auto-Fix + HEAD)
=====================================================================
✅ አዲስ: /api/health ላይ HEAD method ድጋፍ (ለUptimeRobot/Domain Monitor)
✅ አዲስ: Schema ሲበላሽ ሠንጠረዦችን በራስ-ሰር ማደስ
=====================================================================
"""
from fastapi import FastAPI, Depends, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, inspect, func
from sqlalchemy.exc import IntegrityError, OperationalError, DBAPIError
from pydantic import BaseModel, Field
from decimal import Decimal, ROUND_DOWN
from typing import Literal, List, Optional
import os
import secrets
import telebot
import threading
import time
import logging
from datetime import datetime, timedelta, timezone

from database import engine, get_db, Base, SessionLocal
from auth import verify_telegram_init_data
import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

secure_random = secrets.SystemRandom()

app = FastAPI(title="Bingo Game API")

ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
AUTO_MIGRATE = os.getenv("AUTO_MIGRATE", "false").lower() == "true"
ALLOWED_ORIGINS_ENV = os.getenv("ALLOWED_ORIGINS", "")
BOT_POLLING_ENABLED = os.getenv("BOT_POLLING_ENABLED", "true").lower() == "true"

if ENVIRONMENT == "production":
    allowed_origins = [o.strip() for o in ALLOWED_ORIGINS_ENV.split(",") if o.strip()]
    if not allowed_origins:
        allowed_origins = ["https://web.telegram.org", "https://t.me"]
        logger.warning("⚠️ ALLOWED_ORIGINS not set, using defaults")
else:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "HEAD"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")

ENGINE_LOCK_ID = 987654321
GAME_CREATE_LOCK_ID = 987654322
BOT_POLLING_LOCK_ID = 987654323
WAITING_TIMEOUT_MINUTES = 30
DRAW_INTERVAL_SECONDS = 5
MAX_NUMBERS = 75
MIN_DEPOSIT = 10
MAX_DEPOSIT = 50000

MIN_CARDS_TO_START = 2

REQUIRED_TABLES = {
    "users", "games", "cards",
    "transactions", "audit_logs", "ledger_entries",
}

if not BOT_TOKEN:
    logger.warning("⚠️ TELEGRAM_BOT_TOKEN is not set!")
if not ADMIN_ID:
    logger.warning("⚠️ ADMIN_ID is not set!")

logger.info(f"🌍 ENV: {ENVIRONMENT} | AUTO_MIGRATE: {AUTO_MIGRATE} | MIN_CARDS: {MIN_CARDS_TO_START}")

bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        bot.reply_to(message, "ሰላም! የቢንጎ ጨዋታ ቦት እንኳን ደህና መጣህ/ሽ!")

def run_bot():
    if not bot or not BOT_POLLING_ENABLED:
        return
    dedicated_conn = None
    got_lock = False
    try:
        dedicated_conn = engine.raw_connection()
        cursor = dedicated_conn.cursor()
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (BOT_POLLING_LOCK_ID,))
        got_lock = cursor.fetchone()[0]
        cursor.close()
        if not got_lock:
            logger.info("ℹ️ Bot polling skipped (lock held by another worker)")
            return
        logger.info("✅ Bot polling started (this worker holds the lock)")
        bot.polling(non_stop=True, timeout=30)
    except Exception as e:
        logger.error(f"Bot polling error: {e}")
    finally:
        if dedicated_conn:
            try:
                if got_lock:
                    cursor = dedicated_conn.cursor()
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (BOT_POLLING_LOCK_ID,))
                    dedicated_conn.commit()
                    cursor.close()
                    logger.info("✅ Bot advisory lock released")
            except Exception as e:
                logger.error(f"Failed to release bot lock: {e}")
            finally:
                try:
                    dedicated_conn.close()
                except Exception:
                    pass

def add_ledger(db, user, entry_type, amount, ref_type=None, ref_id=None, notes=None):
    entry = models.LedgerEntry(
        user_id=user.id, entry_type=entry_type, amount=amount,
        balance_after=user.balance, reference_type=ref_type,
        reference_id=str(ref_id) if ref_id is not None else None,
        notes=notes,
    )
    db.add(entry)
    return entry

def lock_user(db, user_id):
    return db.query(models.User).filter(models.User.id == user_id).with_for_update().first()

def lock_game(db, game_id):
    return db.query(models.Game).filter(models.Game.id == game_id).with_for_update().first()

def get_admin_id():
    return ADMIN_ID or None

def validate_bingo_card(nums: List[int]) -> tuple:
    if not isinstance(nums, list) or len(nums) != 25:
        return (False, "invalid_length")
    if nums[12] != 0:
        return (False, "center_not_free")
    column_ranges = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75)]
    for r in range(5):
        for c in range(5):
            i = r * 5 + c
            if i == 12:
                continue
            n = nums[i]
            if type(n) is not int:
                return (False, f"non_integer_at_{i}")
            if n == 0:
                return (False, f"zero_at_{i}")
            low, high = column_ranges[c]
            if not (low <= n <= high):
                return (False, f"out_of_range_at_{i}_value_{n}_col_{c}")
    non_zero = [n for i, n in enumerate(nums) if i != 12]
    if len(non_zero) != len(set(non_zero)):
        return (False, "duplicate_numbers")
    return (True, None)

def check_card_winner(nums: List[int], called_set: set) -> bool:
    is_valid, _ = validate_bingo_card(nums)
    if not is_valid:
        return False
    grid = [nums[i * 5:(i + 1) * 5] for i in range(5)]
    grid[2][2] = 0
    if any(all(grid[r][c] == 0 or grid[r][c] in called_set for c in range(5)) for r in range(5)):
        return True
    if any(all(grid[r][c] == 0 or grid[r][c] in called_set for r in range(5)) for c in range(5)):
        return True
    if all(grid[i][i] == 0 or grid[i][i] in called_set for i in range(5)):
        return True
    if all(grid[i][4 - i] == 0 or grid[i][4 - i] in called_set for i in range(5)):
        return True
    return False

def parse_called_numbers(called_str: Optional[str]) -> Optional[set]:
    if called_str is None or called_str.strip() == "":
        return set()
    parts = called_str.split(",")
    called = set()
    try:
        for part in parts:
            part = part.strip()
            if not part:
                return None
            n = int(part)
            if str(n) != part:
                return None
            if not 1 <= n <= MAX_NUMBERS:
                return None
            if n in called:
                return None
            called.add(n)
    except (ValueError, TypeError):
        return None
    return called

async def get_current_user(x_telegram_init_data: str = Header(None), db: Session = Depends(get_db)):
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="የቦት ቶከን አልተዋቀረም")
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="የማንነት ማረጋገጫ የለም")
    tg_user = verify_telegram_init_data(x_telegram_init_data, BOT_TOKEN)
    if not tg_user:
        raise HTTPException(status_code=401, detail="የተሳሳተ ማረጋገጫ")
    tg_id = str(tg_user.get("id"))
    user = db.query(models.User).filter(models.User.telegram_id == tg_id).first()
    if not user:
        try:
            user = models.User(telegram_id=tg_id, username=tg_user.get("username"), balance=Decimal("0.00"))
            db.add(user)
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            user = db.query(models.User).filter(models.User.telegram_id == tg_id).first()
            if not user:
                raise HTTPException(status_code=500, detail="የተጠቃሚ ፍጠራ ስህተት")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="አካውንትዎ ታግዷል")
    return user

async def require_admin(user: models.User = Depends(get_current_user)):
    aid = get_admin_id()
    if not aid:
        raise HTTPException(status_code=503, detail="ADMIN_ID አልተዋቀረም")
    if user.telegram_id != aid:
        raise HTTPException(status_code=403, detail="የAdmin ፈቃድ የለዎትም")
    return user

class DepositRequest(BaseModel):
    amount: Decimal = Field(..., ge=MIN_DEPOSIT, le=MAX_DEPOSIT, max_digits=12, decimal_places=2)
    method: Literal["ቴሌብር", "ሲቢኢ ብር"]
    reference: str = Field(..., min_length=1, max_length=100)

class BuyCardRequest(BaseModel):
    game_id: int = Field(..., gt=0)

def _cancel_game_with_refund(db, game_id: int):
    game = lock_game(db, game_id)
    if not game or game.refunded:
        return (0, True)
    cards = db.query(models.Card).filter(
        models.Card.game_id == game_id,
        models.Card.refunded == False
    ).with_for_update().all()
    refunded_count = 0
    for card in cards:
        existing_refund = db.query(models.LedgerEntry).filter(
            models.LedgerEntry.user_id == card.user_id,
            models.LedgerEntry.entry_type == "refund",
            models.LedgerEntry.reference_type == "card",
            models.LedgerEntry.reference_id == str(card.id)
        ).first()
        if existing_refund:
            ledger_amount = Decimal(str(existing_refund.amount))
            card_amount = Decimal(str(card.price_paid))
            if ledger_amount != card_amount:
                logger.critical(f"Refund mismatch card={card.id}")
                continue
            card.refunded = True
            card.refunded_at = datetime.now(timezone.utc)
            refunded_count += 1
            continue
        nested = db.begin_nested()
        try:
            user = lock_user(db, card.user_id)
            if not user:
                nested.rollback()
                continue
            balance_before = Decimal(str(user.balance))
            user.balance = balance_before + card.price_paid
            add_ledger(db, user, "refund", card.price_paid, ref_type="card", ref_id=card.id, notes=f"ጨዋታ #{game_id} ሰረዘ")
            nested.commit()
            card.refunded = True
            card.refunded_at = datetime.now(timezone.utc)
            refunded_count += 1
        except IntegrityError:
            nested.rollback()
            recheck = db.query(models.LedgerEntry).filter(
                models.LedgerEntry.user_id == card.user_id,
                models.LedgerEntry.entry_type == "refund",
                models.LedgerEntry.reference_type == "card",
                models.LedgerEntry.reference_id == str(card.id)
            ).first()
            if recheck:
                if Decimal(str(recheck.amount)) != Decimal(str(card.price_paid)):
                    continue
                card.refunded = True
                card.refunded_at = datetime.now(timezone.utc)
                refunded_count += 1
        except Exception as e:
            nested.rollback()
            logger.error(f"Refund error card {card.id}: {e}")
    total_cards = db.query(models.Card).filter(models.Card.game_id == game_id).count()
    refunded_total = db.query(models.Card).filter(
        models.Card.game_id == game_id, models.Card.refunded == True
    ).count()
    is_complete = (total_cards == 0) or (refunded_total == total_cards)
    if is_complete:
        game.refunded = True
        game.status = "cancelled"
        game.finished_at = datetime.now(timezone.utc)
    else:
        logger.warning(f"Game {game_id}: {refunded_total}/{total_cards} refunded INCOMPLETE")
    return (refunded_count, is_complete)

@app.get("/")
def read_root():
    return FileResponse("templates/index.html")

@app.get("/api/status")
def api_status():
    return {"message": "የቢንጎ ጨዋታ ጀርባ ስርዓት እየሰራ ነው!"}

# ✅ አዲስ: HEAD method ድጋፍ (ለሞኒተሪንግ አገልግሎቶች)
@app.api_route("/api/health", methods=["GET", "HEAD"])
def health_check():
    """ውጫዊ የሞኒተሪንግ አገልግሎቶች ሰርቨሩን ንቁ ለማድረግ የሚጠቀሙበት"""
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})

@app.get("/api/game/current/state")
def get_or_create_current_game(db: Session = Depends(get_db)):
    db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": GAME_CREATE_LOCK_ID})
    game = db.query(models.Game).filter(
        models.Game.status.in_(["waiting", "playing"])
    ).order_by(models.Game.id.desc()).first()
    if game and game.status == "waiting" and game.created_at:
        if datetime.now(timezone.utc) - game.created_at > timedelta(minutes=WAITING_TIMEOUT_MINUTES):
            _, is_complete = _cancel_game_with_refund(db, game.id)
            if not is_complete:
                logger.critical(f"Game {game.id} refund INCOMPLETE. Partial refunds kept.")
                raise HTTPException(status_code=503, detail="የቀድሞ ጨዋታ ገንዘብ መመለስ አልተሟላም።")
            game = None
    if not game:
        prev_game = db.query(models.Game).filter(
            models.Game.rollover_jackpot > 0,
            models.Game.status == "finished"
        ).order_by(models.Game.id.desc()).with_for_update().first()
        initial_jackpot = Decimal("0.00")
        rollover_received = Decimal("0.00")
        if prev_game and prev_game.rollover_jackpot > 0:
            initial_jackpot = prev_game.rollover_jackpot
            rollover_received = prev_game.rollover_jackpot
            prev_game.rollover_jackpot = Decimal("0.00")
            prev_game.rollover_transferred = True
        game = models.Game(
            status="waiting",
            jackpot=initial_jackpot,
            original_jackpot=initial_jackpot,
            rollover_received=rollover_received,
            card_price=Decimal("10.00")
        )
        db.add(game)
    db.commit()
    db.refresh(game)
    player_count = db.query(models.Card).filter(models.Card.game_id == game.id).count()
    return {
        "id": game.id, "status": game.status,
        "jackpot": float(game.jackpot or 0),
        "card_price": float(game.card_price or 10),
        "call_count": game.call_count,
        "called_numbers": game.called_numbers or "",
        "last_number": game.last_number,
        "players_count": player_count
    }

@app.get("/api/me")
def get_me(user: models.User = Depends(get_current_user)):
    aid = get_admin_id()
    return {
        "id": user.id, "telegram_id": user.telegram_id,
        "username": user.username, "balance": float(user.balance),
        "is_admin": bool(aid and user.telegram_id == aid)
    }

@app.get("/api/my_card/{game_id}")
def get_my_card(game_id: int, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    card = db.query(models.Card).filter(
        models.Card.user_id == user.id,
        models.Card.game_id == game_id
    ).first()
    if not card:
        return {"has_card": False}
    return {"has_card": True, "card_id": card.id, "numbers": card.numbers, "is_winner": card.is_winner}

@app.post("/api/deposit")
def request_deposit(req: DepositRequest, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    clean_reference = req.reference.strip()
    if not clean_reference:
        raise HTTPException(status_code=422, detail="የደረሰኝ ቁጥሩ ባዶ መሆን የለበትም")
    new_trans = models.Transaction(
        user_id=user.id, amount=Decimal(str(req.amount)),
        method=req.method, reference=clean_reference, status="pending"
    )
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
    if not game:
        raise HTTPException(status_code=404, detail="ጨዋታው አልተገኘም")
    if game.status != "waiting":
        raise HTTPException(status_code=400, detail="ጨዋታው ተጀምሯል ወይም ተጠናቋል")
    locked_user = lock_user(db, user.id)
    card_price = game.card_price or Decimal("10.00")
    if locked_user.balance < card_price:
        raise HTTPException(status_code=400, detail="በቂ ባላንስ የለዎትም")
    existing_card = db.query(models.Card).filter(
        models.Card.user_id == locked_user.id,
        models.Card.game_id == req.game_id
    ).first()
    if existing_card:
        raise HTTPException(status_code=400, detail="በዚህ ጨዋታ ካርድ ገዝተዋል")
    columns = [
        secure_random.sample(range(1, 16), 5),
        secure_random.sample(range(16, 31), 5),
        secure_random.sample(range(31, 46), 5),
        secure_random.sample(range(46, 61), 5),
        secure_random.sample(range(61, 76), 5),
    ]
    nums = [columns[c][r] for r in range(5) for c in range(5)]
    nums[12] = 0
    is_valid, err = validate_bingo_card(nums)
    if not is_valid:
        logger.critical(f"Card generation failed: {err}")
        raise HTTPException(status_code=500, detail="የካርድ ፍጠራ ስህተት")
    card_numbers = ",".join(map(str, nums))
    nested = db.begin_nested()
    try:
        locked_user.balance = locked_user.balance - card_price
        new_card = models.Card(
            user_id=locked_user.id, game_id=req.game_id,
            numbers=card_numbers, price_paid=card_price
        )
        db.add(new_card)
        db.flush()
        add_ledger(db, locked_user, "card_purchase", -card_price, ref_type="card", ref_id=new_card.id, notes=f"ጨዋታ #{game.id}")
        nested.commit()
    except IntegrityError:
        nested.rollback()
        raise HTTPException(status_code=400, detail="ድግግሞሽ ተገኝቷል!")
    except Exception as e:
        nested.rollback()
        logger.error(f"Buy card error: {e}")
        raise HTTPException(status_code=500, detail="የውስጥ ስህተት")
    total_cards = db.query(models.Card).filter(models.Card.game_id == req.game_id).count()
    game.jackpot = (game.jackpot or Decimal("0.00")) + card_price
    if total_cards >= MIN_CARDS_TO_START and game.status == "waiting":
        game.status = "playing"
        game.started_at = datetime.now(timezone.utc)
        game.last_drawn_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "ካርድ ተገዝቷል!", "balance": float(locked_user.balance), "card": card_numbers}

@app.get("/api/game/{game_id}")
def get_game_state(game_id: int, db: Session = Depends(get_db)):
    game = db.query(models.Game).filter(models.Game.id == game_id).first()
    if not game:
        return {"error": "ጨዋታው አልተገኘም"}
    player_count = db.query(models.Card).filter(models.Card.game_id == game_id).count()
    return {
        "id": game.id, "status": game.status,
        "jackpot": float(game.jackpot or 0),
        "card_price": float(game.card_price or 10),
        "call_count": game.call_count,
        "called_numbers": game.called_numbers or "",
        "last_number": game.last_number,
        "players_count": player_count, "winner_id": game.winner_id
    }

@app.get("/api/admin/pending")
def get_pending_deposits(admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    pending = db.query(models.Transaction).filter(
        models.Transaction.status == "pending"
    ).order_by(models.Transaction.created_at.asc()).all()
    result = []
    for t in pending:
        u = db.query(models.User).filter(models.User.id == t.user_id).first()
        result.append({
            "id": t.id, "user_telegram_id": u.telegram_id if u else "Unknown",
            "username": u.username if u else None,
            "amount": float(t.amount), "method": t.method, "reference": t.reference,
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else ""
        })
    return {"pending": result}

@app.post("/api/admin/approve/{transaction_id}")
def approve_deposit(transaction_id: int, admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    trans = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id
    ).with_for_update().first()
    if not trans:
        raise HTTPException(status_code=404, detail="ግብይቱ አልተገኘም")
    if trans.status != "pending":
        raise HTTPException(status_code=400, detail=f"ግብይቱ {trans.status} ነው")
    if trans.amount < MIN_DEPOSIT or trans.amount > MAX_DEPOSIT:
        raise HTTPException(status_code=400, detail="የተሳሳተ መጠን")
    user = lock_user(db, trans.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ተጠቃሚው አልተገኘም")
    nested = db.begin_nested()
    try:
        user.balance = user.balance + trans.amount
        add_ledger(db, user, "deposit_approved", trans.amount, ref_type="transaction", ref_id=trans.id, notes=trans.method)
        trans.status = "approved"
        trans.reviewed_by = admin.telegram_id
        trans.reviewed_at = datetime.now(timezone.utc)
        db.add(models.AuditLog(
            actor_id=admin.telegram_id, action="approve_deposit",
            target_type="transaction", target_id=str(trans.id),
            details=f"amount={trans.amount}, user_id={user.telegram_id}"
        ))
        nested.commit()
    except IntegrityError:
        nested.rollback()
        raise HTTPException(status_code=400, detail="ግብይቱ አስቀድሞ ጸድቋል")
    db.commit()
    return {"message": "ጸድቋል!", "new_balance": float(user.balance)}

@app.post("/api/admin/reject/{transaction_id}")
def reject_deposit(transaction_id: int, admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    trans = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id
    ).with_for_update().first()
    if not trans:
        raise HTTPException(status_code=404, detail="ግብይቱ አልተገኘም")
    if trans.status != "pending":
        raise HTTPException(status_code=400, detail=f"ግብይቱ {trans.status} ነው")
    trans.status = "rejected"
    trans.reviewed_by = admin.telegram_id
    trans.reviewed_at = datetime.now(timezone.utc)
    db.add(models.AuditLog(
        actor_id=admin.telegram_id, action="reject_deposit",
        target_type="transaction", target_id=str(trans.id)
    ))
    db.commit()
    return {"message": "ተከልክሏል!"}

@app.post("/api/admin/recover_game/{game_id}")
def recover_game(game_id: int, admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    game = lock_game(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="ጨዋታው አልተገኘም")
    if game.payout_completed:
        return {"message": "ጨዋታው አስቀድሞ ተጠናቋል", "status": game.status}
    if game.status != "playing":
        return {"message": f"ጨዋታው '{game.status}' ሁኔታ ላይ ነው።", "payout_completed": False, "recovery_allowed": False, "reason": f"invalid_status:{game.status}"}
    payouts = db.query(models.LedgerEntry).filter(
        models.LedgerEntry.entry_type == "prize_payout",
        models.LedgerEntry.reference_type == "game",
        models.LedgerEntry.reference_id == str(game.id)
    ).all()
    if not payouts:
        return {"message": "ምንም የpayout መዝገብ የለም", "payout_completed": False, "recovery_allowed": False, "reason": "no_payouts"}
    called_set = parse_called_numbers(game.called_numbers)
    if called_set is None:
        return {"message": "⚠️ called_numbers ቅርጸት ትክክል አይደለም", "payout_completed": False, "recovery_allowed": False, "reason": "invalid_called_numbers"}
    payout_total = sum(Decimal(str(p.amount)) for p in payouts)
    expected_jackpot = Decimal(str(game.original_jackpot or "0.00"))
    if expected_jackpot == Decimal("0.00") and payout_total > Decimal("0.00"):
        expected_jackpot = payout_total
    jackpot_match = payout_total == expected_jackpot
    winner_issues = []
    user_payout_count = {}
    for p in payouts:
        if Decimal(str(p.amount)) < Decimal("0.00"):
            winner_issues.append({"user_id": p.user_id, "issue": "negative_payout", "amount": float(p.amount)})
            continue
        user_payout_count[p.user_id] = user_payout_count.get(p.user_id, 0) + 1
        card = db.query(models.Card).filter(
            models.Card.user_id == p.user_id, models.Card.game_id == game.id, models.Card.refunded == False
        ).first()
        if not card:
            winner_issues.append({"user_id": p.user_id, "issue": "no_card_found"})
            continue
        if not card.is_winner:
            winner_issues.append({"user_id": p.user_id, "card_id": card.id, "issue": "is_winner_flag_false"})
            continue
        try:
            nums = [int(x) for x in card.numbers.split(",")]
        except (ValueError, AttributeError):
            winner_issues.append({"user_id": p.user_id, "card_id": card.id, "issue": "invalid_card_numbers"})
            continue
        is_valid, err = validate_bingo_card(nums)
        if not is_valid:
            winner_issues.append({"user_id": p.user_id, "card_id": card.id, "issue": f"invalid_card:{err}"})
            continue
        if not check_card_winner(nums, called_set):
            winner_issues.append({"user_id": p.user_id, "card_id": card.id, "issue": "not_actual_bingo_winner"})
    for uid, cnt in user_payout_count.items():
        if cnt > 1:
            winner_issues.append({"user_id": uid, "issue": "duplicate_payout_per_user", "count": cnt})
    balance_issues = []
    unique_user_ids = {p.user_id for p in payouts}
    for uid in unique_user_ids:
        user = db.query(models.User).filter(models.User.id == uid).first()
        if not user:
            balance_issues.append({"user_id": uid, "issue": "user_not_found"})
            continue
        ledger_sum = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
            models.LedgerEntry.user_id == uid
        ).scalar()
        ledger_sum = Decimal(str(ledger_sum or "0.00"))
        if ledger_sum != Decimal(str(user.balance)):
            balance_issues.append({"user_id": user.telegram_id, "balance": float(user.balance), "ledger_sum": float(ledger_sum), "issue": "balance_mismatch"})
    refunded_cards = db.query(models.Card).filter(models.Card.game_id == game.id, models.Card.refunded == True).count()
    winners_card_count = db.query(models.Card).filter(
        models.Card.game_id == game.id, models.Card.is_winner == True, models.Card.refunded == False
    ).count()
    payout_count_match = winners_card_count == len(payouts)
    all_checks_pass = (
        jackpot_match and len(winner_issues) == 0 and len(balance_issues) == 0
        and refunded_cards == 0 and payout_count_match
    )
    result = {
        "game_id": game.id, "payout_count": len(payouts),
        "payout_total": float(payout_total), "expected_jackpot": float(expected_jackpot),
        "jackpot_match": jackpot_match, "winner_issues": winner_issues,
        "balance_issues": balance_issues, "refunded_cards": refunded_cards,
        "all_checks_pass": all_checks_pass, "recovery_allowed": all_checks_pass,
    }
    if all_checks_pass:
        game.payout_completed = True
        game.status = "finished"
        game.finished_at = datetime.now(timezone.utc)
        game.jackpot = Decimal("0.00")
        if payouts:
            first_payout = min(payouts, key=lambda p: p.id)
            game.winner_id = first_payout.user_id
        db.add(models.AuditLog(
            actor_id=admin.telegram_id, action="recover_game",
            target_type="game", target_id=str(game.id), details=f"Recovery SUCCESS. total={payout_total}"
        ))
        db.commit()
        result["message"] = "✅ ጨዋታው በተሳካ ሁኔታ ተጠናቋል"
        result["payout_completed"] = True
    else:
        result["message"] = "⚠️ የገንዘብ ማረጋገጫዎች አልተሟሉም።"
        result["payout_completed"] = False
    return result

@app.get("/api/admin/reconcile")
def reconcile(admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    issues = []
    users = db.query(models.User).all()
    balance_mismatches = []
    for u in users:
        ledger_sum = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
            models.LedgerEntry.user_id == u.id
        ).scalar()
        ledger_sum = Decimal(str(ledger_sum or "0.00"))
        if ledger_sum != Decimal(str(u.balance)):
            balance_mismatches.append({"user_id": u.telegram_id, "balance": float(u.balance), "ledger_sum": float(ledger_sum)})
    if balance_mismatches:
        issues.append({"type": "balance_vs_ledger", "count": len(balance_mismatches), "details": balance_mismatches[:50]})
    approved_trans = db.query(models.Transaction).filter(models.Transaction.status == "approved").all()
    transaction_issues = []
    for t in approved_trans:
        ledgers = db.query(models.LedgerEntry).filter(
            models.LedgerEntry.entry_type == "deposit_approved",
            models.LedgerEntry.reference_type == "transaction",
            models.LedgerEntry.reference_id == str(t.id)
        ).all()
        if len(ledgers) != 1:
            transaction_issues.append({"transaction_id": t.id, "issue": "missing_ledger" if len(ledgers) == 0 else "duplicate_ledger"})
            continue
        ledger = ledgers[0]
        problems = []
        if ledger.user_id != t.user_id:
            problems.append("user_id_mismatch")
        if Decimal(str(ledger.amount)) != Decimal(str(t.amount)):
            problems.append("amount_mismatch")
        if problems:
            transaction_issues.append({"transaction_id": t.id, "issue": problems})
    if transaction_issues:
        issues.append({"type": "transaction_ledger_mismatch", "count": len(transaction_issues), "details": transaction_issues[:50]})
    orphan_ledgers = []
    approved_ids = {t.id for t in approved_trans}
    all_deposit_ledgers = db.query(models.LedgerEntry).filter(
        models.LedgerEntry.entry_type == "deposit_approved",
        models.LedgerEntry.reference_type == "transaction"
    ).all()
    for ledger in all_deposit_ledgers:
        try:
            trans_id = int(ledger.reference_id) if ledger.reference_id else None
        except (ValueError, TypeError):
            trans_id = None
        if trans_id is None or trans_id not in approved_ids:
            orphan_ledgers.append({"ledger_id": ledger.id, "reference_id": ledger.reference_id})
    if orphan_ledgers:
        issues.append({"type": "orphan_deposit_ledgers", "count": len(orphan_ledgers), "details": orphan_ledgers[:50]})
    all_games = db.query(models.Game).order_by(models.Game.id.asc()).all()
    game_mismatches = []
    for g in all_games:
        if g.status == "cancelled":
            total_cards = db.query(models.Card).filter(models.Card.game_id == g.id).count()
            refunded_cards = db.query(models.Card).filter(models.Card.game_id == g.id, models.Card.refunded == True).count()
            if total_cards > 0 and refunded_cards != total_cards:
                game_mismatches.append({"game_id": g.id, "issue": "incomplete_refund"})
            if total_cards > 0 and refunded_cards == total_cards and not g.refunded:
                game_mismatches.append({"game_id": g.id, "issue": "refunded_flag_mismatch"})
        elif g.status in ["waiting", "playing"]:
            cards_total = db.query(func.coalesce(func.sum(models.Card.price_paid), 0)).filter(
                models.Card.game_id == g.id, models.Card.refunded == False
            ).scalar()
            cards_total = Decimal(str(cards_total or "0.00"))
            current_jackpot = Decimal(str(g.jackpot or "0.00"))
            rollover_received = Decimal(str(g.rollover_received or "0.00"))
            expected_jackpot = rollover_received + cards_total
            if current_jackpot != expected_jackpot:
                game_mismatches.append({"game_id": g.id, "issue": "jackpot_mismatch", "current": float(current_jackpot), "expected": float(expected_jackpot)})
        elif g.status == "finished":
            payouts = db.query(models.LedgerEntry).filter(
                models.LedgerEntry.entry_type == "prize_payout",
                models.LedgerEntry.reference_type == "game",
                models.LedgerEntry.reference_id == str(g.id)
            ).all()
            if not g.payout_completed:
                if payouts:
                    game_mismatches.append({"game_id": g.id, "issue": "payout_exists_but_not_completed", "recovery_endpoint": f"/api/admin/recover_game/{g.id}"})
                else:
                    game_mismatches.append({"game_id": g.id, "issue": "finished_but_not_completed"})
            else:
                if payouts:
                    payout_user_ids = []
                    for p in payouts:
                        if Decimal(str(p.amount)) < Decimal("0.00"):
                            game_mismatches.append({"game_id": g.id, "issue": "negative_payout", "ledger_id": p.id})
                        winner_card = db.query(models.Card).filter(
                            models.Card.user_id == p.user_id, models.Card.game_id == g.id,
                            models.Card.is_winner == True, models.Card.refunded == False
                        ).first()
                        if not winner_card:
                            game_mismatches.append({"game_id": g.id, "issue": "payout_without_winner_card", "user_id": p.user_id})
                        payout_user_ids.append(p.user_id)
                    if len(payout_user_ids) != len(set(payout_user_ids)):
                        game_mismatches.append({"game_id": g.id, "issue": "duplicate_payout_per_user"})
                    payout_sum = sum(Decimal(str(p.amount)) for p in payouts)
                    rollover_received = Decimal(str(g.rollover_received or "0.00"))
                    cards_total = db.query(func.coalesce(func.sum(models.Card.price_paid), 0)).filter(
                        models.Card.game_id == g.id, models.Card.refunded == False
                    ).scalar()
                    cards_total = Decimal(str(cards_total or "0.00"))
                    expected_total = rollover_received + cards_total
                    if payout_sum != expected_total:
                        game_mismatches.append({"game_id": g.id, "issue": "payout_sum_mismatch", "payout_sum": float(payout_sum), "expected": float(expected_total)})
                    if g.winner_id is None:
                        game_mismatches.append({"game_id": g.id, "issue": "payout_without_winner_id"})
                    elif g.winner_id not in payout_user_ids:
                        game_mismatches.append({"game_id": g.id, "issue": "winner_id_not_in_payouts"})
                else:
                    transferred = getattr(g, "rollover_transferred", False)
                    rollover_j = Decimal(str(g.rollover_jackpot or "0.00"))
                    if rollover_j <= Decimal("0.00") and not transferred:
                        game_mismatches.append({"game_id": g.id, "issue": "finished_no_winner_no_rollover"})
    if game_mismatches:
        issues.append({"type": "game_state_mismatch", "count": len(game_mismatches), "details": game_mismatches[:50]})
    duplicate_entries = db.query(
        models.LedgerEntry.user_id, models.LedgerEntry.entry_type,
        models.LedgerEntry.reference_type, models.LedgerEntry.reference_id,
        func.count(models.LedgerEntry.id).label("cnt")
    ).group_by(
        models.LedgerEntry.user_id, models.LedgerEntry.entry_type,
        models.LedgerEntry.reference_type, models.LedgerEntry.reference_id
    ).having(func.count(models.LedgerEntry.id) > 1).all()
    if duplicate_entries:
        issues.append({"type": "duplicate_ledger_entries", "count": len(duplicate_entries),
            "details": [{"user_id": d.user_id, "entry_type": d.entry_type, "reference_id": d.reference_id, "count": d.cnt} for d in duplicate_entries[:50]]})
    return {
        "checked_users": len(users), "checked_games": len(all_games),
        "checked_transactions": len(approved_trans),
        "issues_found": len(issues), "issues": issues
    }

def bingo_engine_loop():
    while True:
        try:
            time.sleep(DRAW_INTERVAL_SECONDS)
        except Exception as e:
            logger.error(f"Sleep error: {e}")
            continue
        dedicated_conn = None
        got_lock = False
        try:
            try:
                dedicated_conn = engine.raw_connection()
            except (OperationalError, DBAPIError) as db_err:
                logger.warning(f"⚠️ Engine DB connection failed: {db_err}. Retrying in next tick...")
                continue
            cursor = dedicated_conn.cursor()
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (ENGINE_LOCK_ID,))
            got_lock = cursor.fetchone()[0]
            cursor.close()
            if not got_lock:
                continue
            db = SessionLocal()
            try:
                process_engine_tick(db)
                db.commit()
            except Exception as tick_error:
                try:
                    db.rollback()
                except Exception:
                    pass
                logger.error(f"Engine tick error: {tick_error}")
            finally:
                try:
                    db.close()
                except Exception:
                    pass
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
                except Exception as e:
                    logger.error(f"Engine unlock error: {e}")
                finally:
                    try:
                        dedicated_conn.close()
                    except Exception:
                        pass

def process_engine_tick(db):
    old_games = db.query(models.Game).filter(models.Game.status == "waiting").all()
    for og in old_games:
        if og.created_at and datetime.now(timezone.utc) - og.created_at > timedelta(minutes=WAITING_TIMEOUT_MINUTES):
            _, is_complete = _cancel_game_with_refund(db, og.id)
            if not is_complete:
                logger.critical(f"Game {og.id} refund INCOMPLETE")
    games = db.query(models.Game).filter(models.Game.status == "playing").with_for_update().all()
    for game in games:
        existing_payout = db.query(models.LedgerEntry.id).filter(
            models.LedgerEntry.entry_type == "prize_payout",
            models.LedgerEntry.reference_type == "game",
            models.LedgerEntry.reference_id == str(game.id)
        ).first()
        if existing_payout and not game.payout_completed:
            logger.critical(f"Game {game.id} FROZEN.")
            continue
        if game.last_drawn_at:
            elapsed = (datetime.now(timezone.utc) - game.last_drawn_at).total_seconds()
            if elapsed < DRAW_INTERVAL_SECONDS:
                continue
        called_set = parse_called_numbers(game.called_numbers)
        if called_set is None:
            logger.error(f"Game {game.id} corrupt called_numbers: '{game.called_numbers}'. Skipping draw.")
            continue
        called_list = sorted(called_set)
        if len(called_list) >= MAX_NUMBERS:
            _finish_game_no_winner(db, game)
            continue
        available = [n for n in range(1, MAX_NUMBERS + 1) if n not in called_set]
        if not available:
            _finish_game_no_winner(db, game)
            continue
        new_num = secure_random.choice(available)
        called_list.append(new_num)
        game.called_numbers = ",".join(str(x) for x in called_list)
        game.last_number = new_num
        game.call_count = len(called_list)
        game.last_drawn_at = datetime.now(timezone.utc)
        check_winners(db, game, set(called_list))

def _finish_game_no_winner(db, game):
    if game.payout_completed:
        return
    game.original_jackpot = game.jackpot or Decimal("0.00")
    game.rollover_jackpot = (game.rollover_jackpot or Decimal("0.00")) + (game.jackpot or Decimal("0.00"))
    game.jackpot = Decimal("0.00")
    game.payout_completed = True
    game.status = "finished"
    game.finished_at = datetime.now(timezone.utc)

def check_winners(db, game, called_set):
    if game.payout_completed or game.status != "playing":
        return
    game = lock_game(db, game.id)
    if not game or game.payout_completed or game.status != "playing":
        return
    existing_payouts = db.query(models.LedgerEntry).filter(
        models.LedgerEntry.entry_type == "prize_payout",
        models.LedgerEntry.reference_type == "game",
        models.LedgerEntry.reference_id == str(game.id)
    ).all()
    if existing_payouts:
        logger.critical(f"Game {game.id} existing payouts.")
        return
    cards = db.query(models.Card).filter(
        models.Card.game_id == game.id, models.Card.refunded.is_(False)
    ).order_by(models.Card.id.asc()).with_for_update().all()
    winners = []
    for card in cards:
        try:
            nums = [int(x) for x in card.numbers.split(",")]
        except (ValueError, AttributeError):
            continue
        if check_card_winner(nums, called_set):
            winners.append(card)
    if not winners:
        return
    jackpot = Decimal(str(game.jackpot or "0.00")).quantize(Decimal("0.01"))
    if jackpot <= Decimal("0.00"):
        logger.critical(f"Game {game.id}: jackpot {jackpot}.")
        return
    winners.sort(key=lambda c: c.id)
    n = len(winners)
    share = (jackpot / Decimal(n)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    remainder = jackpot - (share * n)
    payout_plan = []
    for i, card in enumerate(winners):
        amount = share + (remainder if i == 0 else Decimal("0.00"))
        payout_plan.append((card, amount))
    total_paid = Decimal("0.00")
    for card, amount in payout_plan:
        user = lock_user(db, card.user_id)
        if not user:
            raise RuntimeError(f"Winner user {card.user_id} not found")
        if card.game_id != game.id:
            raise RuntimeError(f"Card {card.id} wrong game")
        user.balance = Decimal(str(user.balance)) + amount
        add_ledger(db, user, "prize_payout", amount, ref_type="game", ref_id=game.id, notes=f"payout card {card.id} of game {game.id}")
        card.is_winner = True
        total_paid += amount
    if total_paid != jackpot:
        raise RuntimeError(f"Payout total {total_paid} != jackpot {jackpot}")
    game.winner_id = winners[0].user_id
    game.status = "finished"
    game.finished_at = datetime.now(timezone.utc)
    game.payout_completed = True
    game.original_jackpot = jackpot
    game.jackpot = Decimal("0.00")
    logger.info(f"Game {game.id}: payout complete. winners={n}, total={total_paid}")

def validate_schema():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names(schema="public"))
    missing_tables = sorted(REQUIRED_TABLES - existing_tables)
    if missing_tables:
        return (False, f"Missing tables: {missing_tables}")
    required_columns = {
        "users": {"id", "telegram_id", "balance", "is_banned", "created_at"},
        "games": {"id", "status", "jackpot", "original_jackpot", "rollover_jackpot",
                  "rollover_received", "rollover_transferred", "card_price",
                  "payout_completed", "refunded"},
        "cards": {"id", "user_id", "game_id", "numbers", "price_paid", "is_winner", "refunded", "refunded_at"},
        "transactions": {"id", "user_id", "amount", "method", "reference", "status", "reviewed_by", "reviewed_at"},
        "ledger_entries": {"id", "user_id", "entry_type", "amount", "balance_after", "reference_type", "reference_id"},
        "audit_logs": {"id", "actor_id", "action", "target_type", "target_id"},
    }
    missing_columns = {}
    for table, required_cols in required_columns.items():
        actual_cols = {c["name"] for c in inspector.get_columns(table)}
        missing = required_cols - actual_cols
        if missing:
            missing_columns[table] = sorted(missing)
    if missing_columns:
        return (False, f"Missing columns: {missing_columns}")
    return (True, "All checks passed")

@app.on_event("startup")
def startup_event():
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names(schema="public"))

        # ✅ 1. Migration ያስኪድ
        if "alembic_version" in existing_tables:
            try:
                from alembic.config import Config
                from alembic import command
                logger.info("🔄 Running alembic upgrade head...")
                alembic_cfg = Config("alembic.ini")
                command.upgrade(alembic_cfg, "head")
                logger.info("✅ Alembic migration completed")
            except Exception as mig_err:
                logger.warning(f"⚠️ Alembic migration failed: {mig_err}")

        # ✅ 2. ሠንጠረዦች መኖራቸውን አረጋግጥ
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names(schema="public"))
        missing_tables = sorted(REQUIRED_TABLES - existing_tables)

        if missing_tables:
            logger.warning(f"⚠️ Missing tables: {missing_tables}")
            Base.metadata.create_all(bind=engine)
            logger.info("✅ create_all completed")

        # ✅ 3. Schema validation + ማስተካከያ (አዲስ)
        is_valid, message = validate_schema()
        if is_valid:
            logger.info("✅ Schema validation passed")
        else:
            logger.warning(f"⚠️ Schema invalid: {message}")
            logger.warning("🔧 Dropping and recreating all tables to fix schema...")
            # ሠንጠረዦችን አጥፍቶ እንደገና ይፈጥራል
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            logger.info("✅ All tables recreated with correct schema")

            # እንደገና ያረጋግጣል
            is_valid_after, message_after = validate_schema()
            if is_valid_after:
                logger.info("✅ Schema validation passed after recreation")
            else:
                logger.error(f"❌ Schema still invalid: {message_after}")

        # ✅ 4. Connection test
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("✅ Database connection verified")

    except Exception:
        logger.exception("❌ Startup failed.")
        raise

    if bot:
        threading.Thread(target=run_bot, daemon=True).start()
        logger.info("✅ Bot thread started")

    threading.Thread(target=bingo_engine_loop, daemon=True).start()
    logger.info("✅ Bingo engine started.")

    logger.info("✅ Bingo backend started successfully.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
