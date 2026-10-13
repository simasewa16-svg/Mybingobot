"""
=====================================================================
✅ የBingo ጨዋታ ጀርባ ስርዓት (main.py) - v2.0
=====================================================================
ዋና የደህንነት መርሆች፦
1. ሁሉም የገንዘብ ሥራዎች Atomic (Savepoint)
2. ድግግሞሽ መከላከያ (UniqueConstraint + Pre-check + IntegrityError)
3. Row-level Locking (with_for_update)
4. Advisory Lock አንድ ንቁ ጨዋታ ብቻ
5. Audit Log ለሁሉም Admin ድርጊቶች
6. ✅ Payout Atomicity - Payout plan አንድ ጊዜ ይሰላል፣ ሁሉም አሸናፊዎች አብረው ይከፈላሉ
7. ✅ Refund Completeness - ሁሉም ካርዶች እስኪመለሱ ድረስ ጨዋታ አይዘጋም
8. ✅ Correct Routes - /api/game/current/state እና /api/admin/reconcile
=====================================================================
"""
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, condecimal
from decimal import Decimal, ROUND_DOWN
import os
import telebot
import threading
import time
import random
import logging
from datetime import datetime, timedelta

from database import engine, get_db, Base, SessionLocal
from auth import verify_telegram_init_data
import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ ሠንጠረዦች በ Alembic Migration ይፈጠራሉ

app = FastAPI(title="Bingo Game API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== ማዋቀሪያ ====================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")
ENGINE_LOCK_ID = 987654321
GAME_CREATE_LOCK_ID = 987654322
WAITING_TIMEOUT_MINUTES = 30
DRAW_INTERVAL_SECONDS = 5
MAX_NUMBERS = 75

if not BOT_TOKEN:
    logger.warning("⚠️ TELEGRAM_BOT_TOKEN is not set!")
if not ADMIN_ID:
    logger.warning("⚠️ ADMIN_ID is not set! Admin functions disabled.")

bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        bot.reply_to(message, "ሰላም! የቢንጎ ጨዋታ ቦት እንኳን ደህና መጣህ/ሽ!")

def run_bot():
    if bot:
        try:
            bot.polling(non_stop=True, timeout=30)
        except Exception as e:
            logger.error(f"Bot polling error: {e}")

# ==================== Helpers ====================
def add_ledger(db, user, entry_type, amount, ref_type=None, ref_id=None, notes=None):
    """✅ የገንዘብ እንቅስቃሴ መዝግብ - commit አያደርግም!"""
    entry = models.LedgerEntry(
        user_id=user.id,
        entry_type=entry_type,
        amount=amount,
        balance_after=user.balance,
        reference_type=ref_type,
        reference_id=str(ref_id) if ref_id is not None else None,
        notes=notes,
    )
    db.add(entry)
    return entry

def lock_user(db, user_id):
    return db.query(models.User).filter(
        models.User.id == user_id
    ).with_for_update().first()

def lock_game(db, game_id):
    return db.query(models.Game).filter(
        models.Game.id == game_id
    ).with_for_update().first()

def get_admin_id():
    return ADMIN_ID or None

# ==================== Auth ====================
async def get_current_user(
    x_telegram_init_data: str = Header(None),
    db: Session = Depends(get_db)
):
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="የቦት ቶከን አልተዋቀረም")
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="የማንነት ማረጋገጫ የለም")
    tg_user = verify_telegram_init_data(x_telegram_init_data, BOT_TOKEN)
    if not tg_user:
        raise HTTPException(status_code=401, detail="የተሳሳተ ወይም ያለፈበት ማረጋገጫ")

    tg_id = str(tg_user.get("id"))
    user = db.query(models.User).filter(models.User.telegram_id == tg_id).first()
    if not user:
        user = models.User(
            telegram_id=tg_id,
            username=tg_user.get("username"),
            balance=Decimal("0.00")
        )
        db.add(user)
        db.commit()
        db.refresh(user)
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

# ==================== Pydantic ====================
class DepositRequest(BaseModel):
    amount: condecimal(gt=0, max_digits=12, decimal_places=2)
    method: str
    reference: str

class BuyCardRequest(BaseModel):
    game_id: int

# ==================== Game Helpers ====================
def _cancel_game_with_refund(db, game_id: int):
    """
    ✅ ጨዋታ ሰርዞ ገንዘብ መመለስ (Idempotent + Complete)

    🔒 ዋና መርህ፦
    - ሁሉም ካርዶች እስኪመለሱ ድረስ ጨዋታው refunded አይሆንም
    - የተመለሱ ካርዶች በራሳቸው flag ይመዘገባሉ
    - አንድ ካርድ ቢወድቅ ጨዋታ አይዘጋም (ለቀጣይ tick ይተዋል)
    """
    game = lock_game(db, game_id)
    if not game or game.refunded:
        return 0

    cards = db.query(models.Card).filter(
        models.Card.game_id == game_id,
        models.Card.refunded == False
    ).with_for_update().all()

    refunded_count = 0
    failed_count = 0

    for card in cards:
        nested = db.begin_nested()
        try:
            user = lock_user(db, card.user_id)
            if not user:
                nested.rollback()
                failed_count += 1
                continue

            user.balance = user.balance + card.price_paid
            card.refunded = True
            card.refunded_at = datetime.utcnow()
            add_ledger(
                db, user, "refund", card.price_paid,
                ref_type="card", ref_id=card.id,
                notes=f"ጨዋታ #{game_id} ሰረዘ"
            )
            nested.commit()
            refunded_count += 1

        except IntegrityError:
            # ✅ Duplicate refund ledger - አስቀድሞ ተመልሷል
            nested.rollback()
            existing = db.query(models.LedgerEntry).filter(
                models.LedgerEntry.user_id == card.user_id,
                models.LedgerEntry.entry_type == "refund",
                models.LedgerEntry.reference_type == "card",
                models.LedgerEntry.reference_id == str(card.id)
            ).first()
            if existing:
                card.refunded = True
                card.refunded_at = datetime.utcnow()
                refunded_count += 1
            else:
                failed_count += 1
                logger.warning(f"Refund IntegrityError for card {card.id} (unexpected)")
        except Exception as e:
            nested.rollback()
            failed_count += 1
            logger.error(f"Refund error for card {card.id}: {e}")

    # ✅ ሁሉም ካርዶች ከተመለሱ ብቻ ጨዋታውን ዝጋ
    total_cards = db.query(models.Card).filter(
        models.Card.game_id == game_id
    ).count()
    refunded_total = db.query(models.Card).filter(
        models.Card.game_id == game_id,
        models.Card.refunded == True
    ).count()

    if total_cards == 0:
        # ✅ ካርድ የሌለው ጨዋታ - ወዲያውኑ ዝጋ
        game.refunded = True
        game.status = "cancelled"
        game.finished_at = datetime.utcnow()
        logger.info(f"Game {game_id}: no cards, closed immediately.")
    elif refunded_total == total_cards:
        # ✅ ሁሉም ተመልሷል - ጨዋታውን ዝጋ
        game.refunded = True
        game.status = "cancelled"
        game.finished_at = datetime.utcnow()
        logger.info(f"Game {game_id}: all {refunded_count} cards refunded. Game cancelled.")
    else:
        # ⚠️ አንዳንድ ካርዶች አልተመለሱም - ጨዋታ አይዘጋም
        logger.warning(
            f"Game {game_id}: only {refunded_total}/{total_cards} cards refunded. "
            f"Will retry next tick."
        )

    return refunded_count

# ==================== API ====================

@app.get("/")
def read_root():
    return FileResponse("templates/index.html")

@app.get("/api/status")
def api_status():
    return {"message": "የቢንጎ ጨዋታ ጀርባ ስርዓት እየሰራ ነው!"}

# ✅ 1. የአሁኑ ጨዋታ (Race-safe) - /api/game/current/state
@app.get("/api/game/current/state")
def get_or_create_current_game(db: Session = Depends(get_db)):
    db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": GAME_CREATE_LOCK_ID})

    game = db.query(models.Game).filter(
        models.Game.status.in_(["waiting", "playing"])
    ).order_by(models.Game.id.desc()).first()

    if game and game.status == "waiting" and game.created_at:
        if datetime.utcnow() - game.created_at > timedelta(minutes=WAITING_TIMEOUT_MINUTES):
            _cancel_game_with_refund(db, game.id)
            db.commit()
            game = None

    if not game:
        prev_game = db.query(models.Game).filter(
            models.Game.rollover_jackpot > 0,
            models.Game.status == "finished"
        ).order_by(models.Game.id.desc()).first()

        initial_jackpot = Decimal("0.00")
        if prev_game and prev_game.rollover_jackpot > 0:
            initial_jackpot = prev_game.rollover_jackpot
            prev_game.rollover_jackpot = Decimal("0.00")

        game = models.Game(
            status="waiting",
            jackpot=initial_jackpot,
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
    return {
        "has_card": True,
        "card_id": card.id,
        "numbers": card.numbers,
        "is_winner": card.is_winner
    }

# ✅ 2. የክፍያ ጥያቄ (IntegrityError ጠባቂ)
@app.post("/api/deposit")
def request_deposit(req: DepositRequest, user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.method not in ["ቴሌብር", "ሲቢኢ ብር"]:
        raise HTTPException(status_code=400, detail="የተሳሳተ የክፍያ ዘዴ")

    existing = db.query(models.Transaction).filter(
        models.Transaction.reference == req.reference
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="ይህ የደረሰኝ ቁጥር ተጠቅሟል!")

    new_trans = models.Transaction(
        user_id=user.id, amount=Decimal(str(req.amount)),
        method=req.method, reference=req.reference, status="pending"
    )
    db.add(new_trans)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="ይህ የደረሰኝ ቁጥር ተጠቅሟል!")
    return {"message": "የክፍያ ጥያቄዎ ተልኳል።"}

# ✅ 3. ካርድ መግዛት (Atomic + Savepoint)
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
        raise HTTPException(status_code=400, detail="በዚህ ጨዋታ አስቀድመው ካርድ ገዝተዋል")

    columns = [random.sample(range(low, high+1), 5) for low, high in [(1,15),(16,30),(31,45),(46,60),(61,75)]]
    nums = [columns[c][r] for r in range(5) for c in range(5)]
    card_numbers = ",".join(map(str, nums))

    nested = db.begin_nested()
    try:
        locked_user.balance = locked_user.balance - card_price
        new_card = models.Card(
            user_id=locked_user.id,
            game_id=req.game_id,
            numbers=card_numbers,
            price_paid=card_price
        )
        db.add(new_card)
        db.flush()
        add_ledger(
            db, locked_user, "card_purchase", -card_price,
            ref_type="card", ref_id=new_card.id,
            notes=f"ጨዋታ #{game.id}"
        )
        nested.commit()
    except IntegrityError:
        nested.rollback()
        raise HTTPException(status_code=400, detail="ድግግሞሽ ተገኝቷል። እባክዎ እንደገና ይሞክሩ።")
    except Exception as e:
        nested.rollback()
        logger.error(f"Buy card error: {e}")
        raise HTTPException(status_code=500, detail="የውስጥ ስህተት")

    total_cards = db.query(models.Card).filter(models.Card.game_id == req.game_id).count()
    game.jackpot = (game.jackpot or Decimal("0.00")) + card_price

    if total_cards >= 2 and game.status == "waiting":
        game.status = "playing"
        game.started_at = datetime.utcnow()
        game.last_drawn_at = datetime.utcnow()

    db.commit()
    return {
        "message": "ካርድ ተገዝቷል!",
        "balance": float(locked_user.balance),
        "card": card_numbers
    }

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
        "players_count": player_count,
        "winner_id": game.winner_id
    }

# ==================== Admin ====================
@app.get("/api/admin/pending")
def get_pending_deposits(admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    pending = db.query(models.Transaction).filter(
        models.Transaction.status == "pending"
    ).order_by(models.Transaction.created_at.asc()).all()
    result = []
    for t in pending:
        u = db.query(models.User).filter(models.User.id == t.user_id).first()
        result.append({
            "id": t.id,
            "user_telegram_id": u.telegram_id if u else "Unknown",
            "username": u.username if u else None,
            "amount": float(t.amount), "method": t.method,
            "reference": t.reference,
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
        raise HTTPException(status_code=400, detail=f"ግብይቱ {trans.status} ሁኔታ ላይ ነው")
    if trans.amount <= 0:
        raise HTTPException(status_code=400, detail="የተሳሳተ መጠን")

    trans.status = "approved"
    trans.reviewed_by = admin.telegram_id
    trans.reviewed_at = datetime.utcnow()

    user = lock_user(db, trans.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ተጠቃሚው አልተገኘም")

    nested = db.begin_nested()
    try:
        user.balance = user.balance + trans.amount
        add_ledger(
            db, user, "deposit_approved", trans.amount,
            ref_type="transaction", ref_id=trans.id, notes=trans.method
        )
        nested.commit()
    except IntegrityError:
        nested.rollback()
        raise HTTPException(status_code=400, detail="ይህ ግብይት አስቀድሞ ጸድቋል")

    db.add(models.AuditLog(
        actor_id=admin.telegram_id,
        action="approve_deposit",
        target_type="transaction",
        target_id=str(trans.id),
        details=f"amount={trans.amount}, user_id={user.telegram_id}"
    ))
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
        raise HTTPException(status_code=400, detail=f"ግብይቱ {trans.status} ሁኔታ ላይ ነው")
    trans.status = "rejected"
    trans.reviewed_by = admin.telegram_id
    trans.reviewed_at = datetime.utcnow()
    db.add(models.AuditLog(
        actor_id=admin.telegram_id,
        action="reject_deposit",
        target_type="transaction",
        target_id=str(trans.id)
    ))
    db.commit()
    return {"message": "ተከልክሏል!"}

# ✅ 4. Reconciliation - /api/admin/reconcile (ትክክለኛው route + admin required)
@app.get("/api/admin/reconcile")
def reconcile(admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(models.User).all()
    mismatches = []
    for u in users:
        ledger_rows = db.query(models.LedgerEntry).filter(
            models.LedgerEntry.user_id == u.id
        ).with_entities(models.LedgerEntry.amount).all()
        total = sum((row[0] for row in ledger_rows), Decimal("0.00"))
        if total != u.balance:
            mismatches.append({
                "user_id": u.telegram_id,
                "balance": float(u.balance),
                "ledger_sum": float(total),
                "diff": float(u.balance - total)
            })
    return {
        "checked": len(users),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches
    }

# ==================== Bingo Engine ====================
def bingo_engine_loop():
    while True:
        try:
            time.sleep(DRAW_INTERVAL_SECONDS)
            db = SessionLocal()
            try:
                got_lock = db.execute(
                    text("SELECT pg_try_advisory_lock(:id)"),
                    {"id": ENGINE_LOCK_ID}
                ).scalar()
                if not got_lock:
                    db.close()
                    continue
                try:
                    process_engine_tick(db)
                finally:
                    db.execute(
                        text("SELECT pg_advisory_unlock(:id)"),
                        {"id": ENGINE_LOCK_ID}
                    )
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Bingo engine error: {e}")


def process_engine_tick(db):
    old_games = db.query(models.Game).filter(models.Game.status == "waiting").all()
    for og in old_games:
        if og.created_at and datetime.utcnow() - og.created_at > timedelta(minutes=WAITING_TIMEOUT_MINUTES):
            _cancel_game_with_refund(db, og.id)
    db.commit()

    games = db.query(models.Game).filter(
        models.Game.status == "playing"
    ).with_for_update().all()

    for game in games:
        if game.last_drawn_at:
            elapsed = (datetime.utcnow() - game.last_drawn_at).total_seconds()
            if elapsed < DRAW_INTERVAL_SECONDS:
                continue

        called_list = [int(x) for x in game.called_numbers.split(",") if x] if game.called_numbers else []

        if len(called_list) >= MAX_NUMBERS:
            _finish_game_no_winner(db, game)
            db.commit()
            continue

        available = [n for n in range(1, MAX_NUMBERS + 1) if n not in called_list]
        if not available:
            _finish_game_no_winner(db, game)
            db.commit()
            continue

        new_num = random.choice(available)
        called_list.append(new_num)
        game.called_numbers = ",".join(str(x) for x in called_list)
        game.last_number = new_num
        game.call_count = len(called_list)
        game.last_drawn_at = datetime.utcnow()

        check_winners(db, game, set(called_list))
        db.commit()


def _finish_game_no_winner(db, game):
    if game.payout_completed:
        return
    game.rollover_jackpot = (game.rollover_jackpot or Decimal("0.00")) + (game.jackpot or Decimal("0.00"))
    game.jackpot = Decimal("0.00")
    game.payout_completed = True
    game.status = "finished"
    game.finished_at = datetime.utcnow()


def check_winners(db, game, called_set):
    """
    ✅ የBingo ድል ማረጋገጫ + Atomic Idempotent Payout

    🔒 ዋና የደህንነት መርህ፦
    - Payout plan አንድ ጊዜ ብቻ ይሰላል (Recomputation የለም!)
    - ሁሉም አሸናፊዎች በአንድ Atomic Transaction ይከፈላሉ
    - አንዱ ካልተሳካ → ሁሉም rollback → በቀጣይ tick ይሞክራል
    - የቀድሞ ክፍያ ካለ በ plan ውስጥ ይታወቃል (ድግግሞሽ አይፈጽምም)
    """
    if game.payout_completed:
        return

    # ============ 1. አዲስ አሸናፊዎችን ፈልግ ============
    cards = db.query(models.Card).filter(
        models.Card.game_id == game.id,
        models.Card.is_winner == False
    ).all()

    new_winners = []
    for card in cards:
        try:
            nums = [int(x) for x in card.numbers.split(",")]
        except Exception:
            continue
        if len(nums) < 25:
            continue

        grid = [nums[i*5:(i+1)*5] for i in range(5)]
        grid[2][2] = 0

        is_win = False
        for r in range(5):
            if all(grid[r][c] == 0 or grid[r][c] in called_set for c in range(5)):
                is_win = True
                break
        if not is_win:
            for c in range(5):
                if all(grid[r][c] == 0 or grid[r][c] in called_set for r in range(5)):
                    is_win = True
                    break
        if not is_win:
            if all(grid[i][i] == 0 or grid[i][i] in called_set for i in range(5)):
                is_win = True
            elif all(grid[i][4-i] == 0 or grid[i][4-i] in called_set for i in range(5)):
                is_win = True

        if is_win:
            new_winners.append(card)

    if not new_winners:
        return

    # ============ 2. የቀድሞ ክፍያዎችን ፈልግ (Idempotency) ============
    # ✅ ይህ ዋናው P0 fix ነው!
    # የቀድሞ ክፍያ ያላቸውን ካርዶች ለይተን ማውጣት
    already_paid_cards = []
    unpaid_cards = []
    
    for card in new_winners:
        existing = db.query(models.LedgerEntry).filter(
            models.LedgerEntry.user_id == card.user_id,
            models.LedgerEntry.entry_type == "prize_payout",
            models.LedgerEntry.reference_type == "game",
            models.LedgerEntry.reference_id == str(game.id)
        ).first()
        if existing:
            already_paid_cards.append(card)
        else:
            unpaid_cards.append(card)

    # የቀድሞ ክፍያ ያላቸውን ብቻ ምልክት አድርግ
    for card in already_paid_cards:
        card.is_winner = True

    if not unpaid_cards:
        # ሁሉም አስቀድመው ተከፍለዋል
        return

    # ============ 3. ለዘለቀው ካርዶች ብቻ አዲስ Payout Plan ስላ ============
    # ✅ ቀድሞ የተከፈላቸውን ሳይጨምር ስሌት
    total_jackpot = game.jackpot or Decimal("0.00")
    
    # ቀድሞ የተከፈለውን መጠን ቀንስ
    already_paid_amount = Decimal("0.00")
    for card in already_paid_cards:
        entry = db.query(models.LedgerEntry).filter(
            models.LedgerEntry.user_id == card.user_id,
            models.LedgerEntry.entry_type == "prize_payout",
            models.LedgerEntry.reference_type == "game",
            models.LedgerEntry.reference_id == str(game.id)
        ).first()
        if entry:
            already_paid_amount += entry.amount

    # ለቀሪዎቹ የሚከፋፈለው ጠቅላላ
    remaining_jackpot = total_jackpot - already_paid_amount
    if remaining_jackpot < 0:
        remaining_jackpot = Decimal("0.00")

    n_unpaid = len(unpaid_cards)
    if n_unpaid == 0:
        return

    share = (remaining_jackpot / Decimal(n_unpaid)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    remainder = remaining_jackpot - (share * n_unpaid)

    payout_plan = []
    for i, card in enumerate(unpaid_cards):
        amount = share + (remainder if i == 0 else Decimal("0.00"))
        payout_plan.append((card, amount))

    # ============ 4. ሁሉንም በአንድ Atomic Transaction ክፈል ============
    try:
        for card, amount in payout_plan:
            if amount <= 0:
                raise ValueError(f"Invalid payout for card {card.id}: {amount}")

            w = lock_user(db, card.user_id)
            if not w:
                raise ValueError(f"Winner user {card.user_id} not found")

            w.balance = w.balance + amount
            add_ledger(
                db, w, "prize_payout", amount,
                ref_type="game", ref_id=game.id,
                notes=f"payout for card {card.id} of game {game.id}"
            )
            card.is_winner = True

        # ============ 5. ሁሉም ከተከፈሉ በኋላ ጨዋታውን ዝጋ ============
        # ሁሉም ካርዶች አሸናፊ መሆናቸውን አረጋግጥ
        all_winner_count = db.query(models.Card).filter(
            models.Card.game_id == game.id,
            models.Card.is_winner == True
        ).count()
        
        # ✅ የጠቅላላ ክፍያ ድምር ከ jackpot ጋር ማመሳከር
        all_payouts = db.query(models.LedgerEntry).filter(
            models.LedgerEntry.entry_type == "prize_payout",
            models.LedgerEntry.reference_type == "game",
            models.LedgerEntry.reference_id == str(game.id)
        ).with_entities(models.LedgerEntry.amount).all()
        total_paid = sum((row[0] for row in all_payouts), Decimal("0.00"))
        
        if total_paid >= total_jackpot:
            # ✅ ጠቅላላ ክፍያ ከ jackpot ጋር እኩል ወይም የበለጠ - ጨዋታውን ዝጋ
            game.status = "finished"
            game.finished_at = datetime.utcnow()
            game.winner_id = unpaid_cards[0].user_id if unpaid_cards else already_paid_cards[0].user_id
            game.payout_completed = True
            game.jackpot = Decimal("0.00")
            db.commit()
            logger.info(
                f"Game {game.id}: payout complete. "
                f"Total paid={total_paid}, jackpot={total_jackpot}"
            )
        else:
            # አልተጠናቀቀም - በቀጣይ tick ይሞክራል
            db.commit()
            logger.info(
                f"Game {game.id}: partial payout. "
                f"Total paid={total_paid}, jackpot={total_jackpot}. Will continue."
            )

    except Exception as e:
        # ✅ ሁሉም rollback - በሚቀጥለው tick እንደገና ይሞክራል
        db.rollback()
        logger.error(f"Payout failed for game {game.id}: {e}. Will retry next tick.")


# ==================== Startup ====================
@app.on_event("startup")
def startup_event():
    if bot:
        threading.Thread(target=run_bot, daemon=True).start()
    threading.Thread(target=bingo_engine_loop, daemon=True).start()
    logger.info("✅ Bingo backend started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
