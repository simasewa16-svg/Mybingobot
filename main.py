"""
=====================================================================
✅ የBingo ጨዋታ ጀርባ ስርዓት (main.py) - v8.1 FULL SYSTEM
=====================================================================
✅ ሁሉንም ያካትታል:
   - የጨዋታ ሞተር (Bingo engine)
   - የቴሌግራም ቦት
   - የAdmin ስርዓት (multi-admin, permissions, audit)
   - የWithdrawal ስርዓት
   - የተጫዋች ማስተዳደር
   - የFraud flags
   - የሰንጠረዥ እና ታሪክ
=====================================================================
"""
from fastapi import FastAPI, Depends, HTTPException, Header, Request
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
from admin_auth import (
    get_admin_user, has_permission, is_super_admin,
    require_permission, log_admin_action,
    ALL_PERMISSIONS, ROLE_PERMISSIONS, get_admin_permissions,
)
import models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

secure_random = secrets.SystemRandom()

app = FastAPI(title="Bingo Game API")

# =====================================================================
# ✅ የአካባቢ ቅንብሮች
# =====================================================================
ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
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
    allow_methods=["GET", "POST", "HEAD", "DELETE"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SUPER_ADMIN_ID = os.getenv("ADMIN_ID", "")
SUPER_ADMIN_USERNAME = os.getenv("SUPER_ADMIN_USERNAME", "Super Admin")

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

REQUIRED_TABLES = {
    "users", "games", "cards", "transactions",
    "audit_logs", "ledger_entries",
    "withdrawals", "admin_users", "player_notes", "fraud_flags",
}

if not BOT_TOKEN:
    logger.warning("⚠️ TELEGRAM_BOT_TOKEN is not set!")
if not SUPER_ADMIN_ID:
    logger.warning("⚠️ ADMIN_ID is not set!")

logger.info(f"🌍 ENV: {ENVIRONMENT} | MIN_CARDS: {MIN_CARDS_TO_START}")

# =====================================================================
# ✅ Telegram Bot
# =====================================================================
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
            logger.info("ℹ️ Bot polling skipped (lock held)")
            return
        logger.info("✅ Bot polling started")
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
            except Exception as e:
                logger.error(f"Bot unlock error: {e}")
            finally:
                try:
                    dedicated_conn.close()
                except Exception:
                    pass


# =====================================================================
# ✅ Helper ተግባሮች
# =====================================================================
def ensure_super_admin_exists(db: Session):
    """Super Admin መኖሩን ማረጋገጥ"""
    if not SUPER_ADMIN_ID:
        return None
    admin = db.query(models.AdminUser).filter(
        models.AdminUser.telegram_id == SUPER_ADMIN_ID
    ).first()
    if not admin:
        admin = models.AdminUser(
            telegram_id=SUPER_ADMIN_ID,
            display_name=SUPER_ADMIN_USERNAME,
            role="super_admin",
            is_active=True
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        logger.info(f"✅ Super Admin created: {SUPER_ADMIN_ID}")
    return admin


def add_ledger(db, user, entry_type, amount, ref_type=None, ref_id=None, notes=None):
    entry = models.LedgerEntry(
        user_id=user.id,
        entry_type=entry_type,
        amount=amount,
        balance_after=user.balance,
        reference_type=ref_type if ref_type else "system",
        reference_id=str(ref_id) if ref_id is not None else "auto",
        notes=notes,
    )
    db.add(entry)
    return entry


def lock_user(db, user_id):
    return db.query(models.User).filter(models.User.id == user_id).with_for_update().first()


def lock_game(db, game_id):
    return db.query(models.Game).filter(models.Game.id == game_id).with_for_update().first()


# =====================================================================
# ✅ Bingo Card Validation
# =====================================================================
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
                return (False, f"out_of_range_at_{i}")
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


# =====================================================================
# ✅ Authentication
# =====================================================================
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
        raise HTTPException(status_code=401, detail="የተሳሳተ ማረጋገጫ")
    tg_id = str(tg_user.get("id"))
    user = db.query(models.User).filter(models.User.telegram_id == tg_id).first()
    if not user:
        try:
            user = models.User(
                telegram_id=tg_id,
                username=tg_user.get("username"),
                first_name=tg_user.get("first_name"),
                last_name=tg_user.get("last_name"),
                balance=Decimal("0.00")
            )
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


async def require_admin(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """የAdmin ማረጋገጫ (multi-admin)"""
    admin = get_admin_user(db, user.telegram_id)
    # Super Admin ገና ካልተፈጠረ ፍጠር
    if not admin and user.telegram_id == SUPER_ADMIN_ID:
        ensure_super_admin_exists(db)
        admin = get_admin_user(db, user.telegram_id)
    if not admin:
        raise HTTPException(status_code=403, detail="የAdmin ፈቃድ የለዎትም")
    # last_login update
    try:
        admin.last_login = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
    return admin


# =====================================================================
# ✅ Request Models
# =====================================================================
class DepositRequest(BaseModel):
    amount: Decimal = Field(..., ge=MIN_DEPOSIT, le=MAX_DEPOSIT,
                            max_digits=12, decimal_places=2)
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


# =====================================================================
# ✅ Game Cancellation Helper
# =====================================================================
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
            if Decimal(str(existing_refund.amount)) != Decimal(str(card.price_paid)):
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
            user.balance = Decimal(str(user.balance)) + card.price_paid
            add_ledger(db, user, "refund", card.price_paid,
                       ref_type="card", ref_id=card.id,
                       notes=f"ጨዋታ #{game_id} ሰረዘ")
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
    return (refunded_count, is_complete)


# =====================================================================
# ✅ BASIC ROUTES
# =====================================================================
@app.get("/")
def read_root():
    return FileResponse("templates/index.html")


@app.get("/api/status")
def api_status():
    return {"message": "የቢንጎ ጨዋታ ጀርባ ስርዓት እየሰራ ነው!"}


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health_check():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(status_code=503,
                            content={"status": "unhealthy", "error": str(e)})


# =====================================================================
# ✅ GAME ENDPOINTS
# =====================================================================
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


@app.get("/api/me")
def get_me(user: models.User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    admin = get_admin_user(db, user.telegram_id)
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "balance": float(user.balance),
        "is_admin": bool(admin),
        "is_super_admin": bool(admin and is_super_admin(admin))
    }


@app.get("/api/my_card/{game_id}")
def get_my_card(game_id: int,
                user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    card = db.query(models.Card).filter(
        models.Card.user_id == user.id,
        models.Card.game_id == game_id
    ).first()
    if not card:
        return {"has_card": False}
    return {"has_card": True, "card_id": card.id,
            "numbers": card.numbers, "is_winner": card.is_winner}


@app.post("/api/deposit")
def request_deposit(req: DepositRequest,
                    user: models.User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
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
def buy_card(req: BuyCardRequest,
             user: models.User = Depends(get_current_user),
             db: Session = Depends(get_db)):
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
        add_ledger(db, locked_user, "card_purchase", -card_price,
                   ref_type="card", ref_id=new_card.id,
                   notes=f"ጨዋታ #{game.id}")
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
    return {"message": "ካርድ ተገዝቷል!",
            "balance": float(locked_user.balance), "card": card_numbers}


# =====================================================================
# ✅ LEADERBOARD & HISTORY
# =====================================================================
@app.get("/api/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    try:
        results = db.query(
            models.User.id,
            models.User.telegram_id,
            models.User.username,
            models.User.first_name,
            func.coalesce(func.sum(models.LedgerEntry.amount), 0).label("total_won"),
            func.count(models.LedgerEntry.id).label("win_count")
        ).join(
            models.LedgerEntry,
            models.LedgerEntry.user_id == models.User.id
        ).filter(
            models.LedgerEntry.entry_type == "prize_payout"
        ).group_by(
            models.User.id, models.User.telegram_id,
            models.User.username, models.User.first_name
        ).order_by(
            func.sum(models.LedgerEntry.amount).desc()
        ).limit(20).all()
        leaderboard = []
        for i, r in enumerate(results, 1):
            name = r.username or r.first_name or f"User_{str(r.telegram_id)[-4:]}"
            leaderboard.append({
                "rank": i, "username": name,
                "total_won": float(r.total_won),
                "win_count": int(r.win_count)
            })
        return {"leaderboard": leaderboard}
    except Exception as e:
        logger.error(f"Leaderboard error: {e}")
        return {"leaderboard": []}


@app.get("/api/history")
def get_history(user: models.User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    try:
        entries = db.query(models.LedgerEntry).filter(
            models.LedgerEntry.user_id == user.id
        ).order_by(models.LedgerEntry.created_at.desc()).limit(50).all()
        history = []
        for e in entries:
            history.append({
                "id": e.id, "type": e.entry_type,
                "amount": float(e.amount),
                "balance_after": float(e.balance_after),
                "notes": e.notes or "",
                "created_at": e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else ""
            })
        return {"history": history}
    except Exception as e:
        logger.error(f"History error: {e}")
        raise HTTPException(status_code=500, detail="ታሪክ ማምጣት አልተቻለም")


# =====================================================================
# ✅ WITHDRAWAL ENDPOINTS
# =====================================================================
@app.post("/api/withdrawal")
def request_withdrawal(req: WithdrawalRequest,
                       user: models.User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    if req.amount < MIN_WITHDRAWAL:
        raise HTTPException(status_code=400, detail=f"ዝቅተኛ መጠን {MIN_WITHDRAWAL} ብር")
    if req.amount > MAX_WITHDRAWAL:
        raise HTTPException(status_code=400, detail=f"ከፍተኛ መጠን {MAX_WITHDRAWAL} ብር")
    locked_user = lock_user(db, user.id)
    if locked_user.balance < req.amount:
        raise HTTPException(status_code=400, detail="በቂ ባላንስ የለዎትም")
    locked_user.balance = locked_user.balance - req.amount
    withdrawal = models.Withdrawal(
        user_id=locked_user.id, amount=req.amount,
        method=req.method,
        account_number=req.account_number.strip(),
        account_name=req.account_name.strip() if req.account_name else None,
        status="pending"
    )
    db.add(withdrawal)
    db.flush()
    add_ledger(db, locked_user, "withdrawal_pending", -req.amount,
               ref_type="withdrawal", ref_id=withdrawal.id,
               notes=f"ጥያቄ #{withdrawal.id}")
    db.commit()
    db.refresh(withdrawal)
    return {"message": "የማውጣት ጥያቄዎ ተልኳል", "withdrawal_id": withdrawal.id}


@app.get("/api/withdrawal/my")
def my_withdrawals(user: models.User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    withdrawals = db.query(models.Withdrawal).filter(
        models.Withdrawal.user_id == user.id
    ).order_by(models.Withdrawal.created_at.desc()).limit(50).all()
    return {"withdrawals": [{
        "id": w.id, "amount": float(w.amount),
        "method": w.method, "status": w.status,
        "reference": w.reference,
        "created_at": w.created_at.strftime("%Y-%m-%d %H:%M") if w.created_at else "",
        "paid_at": w.paid_at.strftime("%Y-%m-%d %H:%M") if w.paid_at else None
    } for w in withdrawals]}


# =====================================================================
# ✅ ADMIN: Dashboard & Stats
# =====================================================================
@app.get("/api/admin/me")
def get_admin_info(admin: models.AdminUser = Depends(require_admin)):
    return {
        "id": admin.id,
        "telegram_id": admin.telegram_id,
        "display_name": admin.display_name,
        "role": admin.role,
        "is_super": is_super_admin(admin),
        "permissions": get_admin_permissions(admin),
        "all_permissions": ALL_PERMISSIONS
    }


@app.get("/api/admin/stats")
def get_admin_stats(admin: models.AdminUser = Depends(require_admin),
                    db: Session = Depends(get_db)):
    require_permission(admin, "view_dashboard")
    total_players = db.query(models.User).count()
    banned_players = db.query(models.User).filter(models.User.is_banned == True).count()
    flagged_players = db.query(models.User).filter(models.User.is_flagged == True).count()
    pending_deposits = db.query(models.Transaction).filter(
        models.Transaction.status == "pending").count()
    pending_withdrawals = db.query(models.Withdrawal).filter(
        models.Withdrawal.status == "pending").count()
    total_deposited = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
        models.Transaction.status == "approved").scalar() or 0
    total_withdrawn = db.query(func.coalesce(func.sum(models.Withdrawal.amount), 0)).filter(
        models.Withdrawal.status == "approved").scalar() or 0
    total_payouts = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.entry_type == "prize_payout").scalar() or 0
    total_refunds = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.entry_type == "refund").scalar() or 0
    total_games = db.query(models.Game).count()
    active_games = db.query(models.Game).filter(
        models.Game.status.in_(["waiting", "playing"])).count()
    return {
        "players": {"total": total_players, "banned": banned_players,
                    "flagged": flagged_players},
        "pending": {"deposits": pending_deposits,
                    "withdrawals": pending_withdrawals},
        "money": {"total_deposited": float(total_deposited),
                  "total_withdrawn": float(total_withdrawn),
                  "total_payouts": float(total_payouts),
                  "total_refunds": float(total_refunds)},
        "games": {"total": total_games, "active": active_games}
    }


# =====================================================================
# ✅ ADMIN: Deposits
# =====================================================================
@app.get("/api/admin/pending")
def get_pending_deposits(admin: models.AdminUser = Depends(require_admin),
                         db: Session = Depends(get_db)):
    require_permission(admin, "approve_deposits")
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
def approve_deposit(transaction_id: int,
                    admin: models.AdminUser = Depends(require_admin),
                    db: Session = Depends(get_db)):
    require_permission(admin, "approve_deposits")
    trans = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id
    ).with_for_update().first()
    if not trans:
        raise HTTPException(status_code=404, detail="ግብይቱ አልተገኘም")
    if trans.status != "pending":
        raise HTTPException(status_code=400, detail=f"ግብይቱ {trans.status} ነው")
    user = lock_user(db, trans.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="ተጠቃሚው አልተገኘም")
    nested = db.begin_nested()
    try:
        user.balance = user.balance + trans.amount
        add_ledger(db, user, "deposit_approved", trans.amount,
                   ref_type="transaction", ref_id=trans.id, notes=trans.method)
        trans.status = "approved"
        trans.reviewed_by = admin.telegram_id
        trans.reviewed_at = datetime.now(timezone.utc)
        log_admin_action(db, admin, "approve_deposit",
                         target_type="transaction", target_id=trans.id,
                         details=f"amount={trans.amount}")
        nested.commit()
    except IntegrityError:
        nested.rollback()
        raise HTTPException(status_code=400, detail="ግብይቱ አስቀድሞ ጸድቋል")
    db.commit()
    return {"message": "ጸድቋል!", "new_balance": float(user.balance)}


@app.post("/api/admin/reject/{transaction_id}")
def reject_deposit(transaction_id: int,
                   admin: models.AdminUser = Depends(require_admin),
                   db: Session = Depends(get_db)):
    require_permission(admin, "approve_deposits")
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
    log_admin_action(db, admin, "reject_deposit",
                     target_type="transaction", target_id=trans.id)
    db.commit()
    return {"message": "ተከልክሏል!"}


# =====================================================================
# ✅ ADMIN: Withdrawals
# =====================================================================
@app.get("/api/admin/withdrawals")
def list_withdrawals(admin: models.AdminUser = Depends(require_admin),
                     db: Session = Depends(get_db),
                     status: Optional[str] = None):
    require_permission(admin, "approve_withdrawals")
    query = db.query(models.Withdrawal)
    if status:
        query = query.filter(models.Withdrawal.status == status)
    withdrawals = query.order_by(models.Withdrawal.created_at.desc()).limit(100).all()
    result = []
    for w in withdrawals:
        u = db.query(models.User).filter(models.User.id == w.user_id).first()
        result.append({
            "id": w.id, "user_id": w.user_id,
            "user_telegram_id": u.telegram_id if u else "Unknown",
            "username": u.username if u else None,
            "amount": float(w.amount), "method": w.method,
            "account_number": w.account_number,
            "account_name": w.account_name,
            "status": w.status, "reference": w.reference,
            "created_at": w.created_at.strftime("%Y-%m-%d %H:%M") if w.created_at else ""
        })
    return {"withdrawals": result}


@app.post("/api/admin/withdrawal/{wid}/approve")
def approve_withdrawal(wid: int, req: ApproveWithdrawalRequest,
                       admin: models.AdminUser = Depends(require_admin),
                       db: Session = Depends(get_db)):
    require_permission(admin, "approve_withdrawals")
    withdrawal = db.query(models.Withdrawal).filter(
        models.Withdrawal.id == wid
    ).with_for_update().first()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="ጥያቄው አልተገኘም")
    if withdrawal.status != "pending":
        raise HTTPException(status_code=400, detail=f"ጥያቄው {withdrawal.status} ነው")
    withdrawal.status = "approved"
    withdrawal.reference = req.reference.strip()
    withdrawal.reviewed_by = admin.telegram_id
    withdrawal.reviewed_at = datetime.now(timezone.utc)
    withdrawal.paid_at = datetime.now(timezone.utc)
    withdrawal.notes = req.notes
    log_admin_action(db, admin, "approve_withdrawal",
                     target_type="withdrawal", target_id=wid,
                     details=f"amount={withdrawal.amount}, ref={req.reference}")
    db.commit()
    return {"message": "ተፈቅዷል"}


@app.post("/api/admin/withdrawal/{wid}/reject")
def reject_withdrawal(wid: int,
                      admin: models.AdminUser = Depends(require_admin),
                      db: Session = Depends(get_db)):
    require_permission(admin, "approve_withdrawals")
    withdrawal = db.query(models.Withdrawal).filter(
        models.Withdrawal.id == wid
    ).with_for_update().first()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="ጥያቄው አልተገኘም")
    if withdrawal.status != "pending":
        raise HTTPException(status_code=400, detail=f"ጥያቄው {withdrawal.status} ነው")
    user = lock_user(db, withdrawal.user_id)
    if user:
        user.balance = user.balance + withdrawal.amount
        add_ledger(db, user, "withdrawal_refund", withdrawal.amount,
                   ref_type="withdrawal", ref_id=wid,
                   notes=f"ጥያቄ #{wid} ተከልክሏል")
    withdrawal.status = "rejected"
    withdrawal.reviewed_by = admin.telegram_id
    withdrawal.reviewed_at = datetime.now(timezone.utc)
    log_admin_action(db, admin, "reject_withdrawal",
                     target_type="withdrawal", target_id=wid,
                     details=f"amount={withdrawal.amount}")
    db.commit()
    return {"message": "ተከልክሏል እና ባላንስ ተመልሷል"}


# =====================================================================
# ✅ ADMIN: Player Management
# =====================================================================
@app.get("/api/admin/players")
def get_all_players(admin: models.AdminUser = Depends(require_admin),
                    db: Session = Depends(get_db),
                    search: Optional[str] = None,
                    filter_type: Optional[str] = None,
                    sort_by: Optional[str] = "created_at",
                    limit: int = 100):
    require_permission(admin, "view_players")
    query = db.query(models.User)
    if search:
        term = f"%{search}%"
        query = query.filter(
            (models.User.username.ilike(term)) |
            (models.User.telegram_id.ilike(term)) |
            (models.User.first_name.ilike(term))
        )
    if filter_type == "banned":
        query = query.filter(models.User.is_banned == True)
    elif filter_type == "flagged":
        query = query.filter(models.User.is_flagged == True)
    elif filter_type == "new":
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        query = query.filter(models.User.created_at >= week_ago)
    if sort_by == "balance":
        query = query.order_by(models.User.balance.desc())
    else:
        query = query.order_by(models.User.created_at.desc())
    users = query.limit(limit).all()
    result = []
    for u in users:
        total_games = db.query(models.Card).filter(models.Card.user_id == u.id).count()
        total_wins = db.query(models.Card).filter(
            models.Card.user_id == u.id, models.Card.is_winner == True).count()
        total_won = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
            models.LedgerEntry.user_id == u.id,
            models.LedgerEntry.entry_type == "prize_payout").scalar() or 0
        total_deposited = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
            models.Transaction.user_id == u.id,
            models.Transaction.status == "approved").scalar() or 0
        name = u.first_name or u.username or f"User_{u.telegram_id[-4:]}"
        result.append({
            "id": u.id, "telegram_id": u.telegram_id,
            "username": u.username, "display_name": name,
            "balance": float(u.balance),
            "is_banned": u.is_banned, "is_flagged": u.is_flagged,
            "created_at": u.created_at.strftime("%Y-%m-%d") if u.created_at else "",
            "total_games": total_games, "total_wins": total_wins,
            "total_won": float(total_won),
            "total_deposited": float(total_deposited),
            "win_rate": round((total_wins / total_games * 100), 1) if total_games > 0 else 0.0
        })
    return {"players": result, "total": len(result)}


@app.get("/api/admin/player/{user_id}/full")
def get_player_full(user_id: int,
                    admin: models.AdminUser = Depends(require_admin),
                    db: Session = Depends(get_db)):
    require_permission(admin, "view_players")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ተጫዋች አልተገኘም")
    total_games = db.query(models.Card).filter(models.Card.user_id == user.id).count()
    total_wins = db.query(models.Card).filter(
        models.Card.user_id == user.id, models.Card.is_winner == True).count()
    total_won = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
        models.LedgerEntry.user_id == user.id,
        models.LedgerEntry.entry_type == "prize_payout").scalar() or 0
    total_deposited = db.query(func.coalesce(func.sum(models.Transaction.amount), 0)).filter(
        models.Transaction.user_id == user.id,
        models.Transaction.status == "approved").scalar() or 0
    total_withdrawn = db.query(func.coalesce(func.sum(models.Withdrawal.amount), 0)).filter(
        models.Withdrawal.user_id == user.id,
        models.Withdrawal.status == "approved").scalar() or 0
    total_cards_bought = db.query(func.coalesce(func.sum(models.Card.price_paid), 0)).filter(
        models.Card.user_id == user.id).scalar() or 0
    transactions = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id
    ).order_by(models.Transaction.created_at.desc()).limit(20).all()
    cards = db.query(models.Card).filter(
        models.Card.user_id == user.id
    ).order_by(models.Card.created_at.desc()).limit(20).all()
    withdrawals = db.query(models.Withdrawal).filter(
        models.Withdrawal.user_id == user.id
    ).order_by(models.Withdrawal.created_at.desc()).limit(10).all()
    notes = db.query(models.PlayerNote).filter(
        models.PlayerNote.user_id == user.id
    ).order_by(models.PlayerNote.created_at.desc()).limit(10).all()
    name = user.first_name or user.username or f"User_{user.telegram_id[-4:]}"
    return {
        "user": {
            "id": user.id, "telegram_id": user.telegram_id,
            "username": user.username, "first_name": user.first_name,
            "display_name": name, "balance": float(user.balance),
            "is_banned": user.is_banned, "is_flagged": user.is_flagged,
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M") if user.created_at else "",
            "last_active": user.last_active.strftime("%Y-%m-%d %H:%M") if user.last_active else None
        },
        "stats": {
            "total_games": total_games, "total_wins": total_wins,
            "total_won": float(total_won),
            "total_deposited": float(total_deposited),
            "total_withdrawn": float(total_withdrawn),
            "total_cards_bought": float(total_cards_bought),
            "net_profit": float(total_deposited) - float(total_withdrawn),
            "win_rate": round((total_wins / total_games * 100), 1) if total_games > 0 else 0.0
        },
        "transactions": [{"id": t.id, "amount": float(t.amount), "method": t.method,
                          "status": t.status, "reference": t.reference,
                          "created_at": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else ""
                          } for t in transactions],
        "cards": [{"id": c.id, "game_id": c.game_id, "is_winner": c.is_winner,
                   "price_paid": float(c.price_paid),
                   "created_at": c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else ""
                   } for c in cards],
        "withdrawals": [{"id": w.id, "amount": float(w.amount), "method": w.method,
                         "status": w.status, "account_number": w.account_number,
                         "created_at": w.created_at.strftime("%Y-%m-%d %H:%M") if w.created_at else ""
                         } for w in withdrawals],
        "notes": [{"id": n.id, "note": n.note, "author": n.author_name,
                   "is_warning": n.is_warning,
                   "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else ""
                   } for n in notes]
    }


@app.post("/api/admin/player/{user_id}/adjust_balance")
def adjust_balance_v2(user_id: int, req: AdjustBalanceRequest,
                      admin: models.AdminUser = Depends(require_admin),
                      db: Session = Depends(get_db)):
    require_permission(admin, "adjust_balance")
    user = db.query(models.User).filter(models.User.id == user_id).with_for_update().first()
    if not user:
        raise HTTPException(status_code=404, detail="ተጫዋች አልተገኘም")
    if req.amount == 0:
        raise HTTPException(status_code=400, detail="መጠኑ ዜሮ መሆን አይችልም")
    new_balance = Decimal(str(user.balance)) + req.amount
    if new_balance < 0:
        raise HTTPException(status_code=400, detail="ባላንስ ከዜሮ በታች መሆን አይችልም")
    user.balance = new_balance
    db.add(models.LedgerEntry(
        user_id=user.id, entry_type="admin_adjustment",
        amount=req.amount, balance_after=new_balance,
        reference_type="admin", reference_id=admin.telegram_id,
        notes=f"[{admin.display_name}] {req.reason}"
    ))
    log_admin_action(db, admin, "adjust_balance",
                     target_type="user", target_id=user.id,
                     details=f"amount={req.amount}, reason={req.reason}")
    db.commit()
    return {"message": "ተስተካክሏል", "new_balance": float(new_balance)}


@app.post("/api/admin/player/{user_id}/ban")
def ban_player(user_id: int,
               admin: models.AdminUser = Depends(require_admin),
               db: Session = Depends(get_db)):
    require_permission(admin, "ban_players")
    user = db.query(models.User).filter(models.User.id == user_id).with_for_update().first()
    if not user:
        raise HTTPException(status_code=404, detail="ተጫዋች አልተገኘም")
    if user.telegram_id == admin.telegram_id:
        raise HTTPException(status_code=400, detail="ራስዎን ማገድ አይችሉም")
    user.is_banned = not user.is_banned
    action = "ban_player" if user.is_banned else "unban_player"
    log_admin_action(db, admin, action,
                     target_type="user", target_id=user.id,
                     details=f"user={user.telegram_id}")
    db.commit()
    return {"message": "ተገድቷል" if user.is_banned else "ከእገዳ ተነስቷል",
            "is_banned": user.is_banned}


@app.post("/api/admin/player/{user_id}/note")
def add_player_note(user_id: int, req: AddPlayerNoteRequest,
                    admin: models.AdminUser = Depends(require_admin),
                    db: Session = Depends(get_db)):
    require_permission(admin, "view_players")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="ተጫዋች አልተገኘም")
    note = models.PlayerNote(
        user_id=user.id, author_id=admin.telegram_id,
        author_name=admin.display_name,
        note=req.note, is_warning=req.is_warning
    )
    db.add(note)
    if req.is_warning:
        user.is_flagged = True
    log_admin_action(db, admin, "add_player_note",
                     target_type="user", target_id=user.id,
                     details=req.note[:100])
    db.commit()
    return {"message": "ማስታወሻ ተጨምሯል"}


# =====================================================================
# ✅ ADMIN: Manage Admins
# =====================================================================
@app.post("/api/admin/create")
def create_admin(req: CreateAdminRequest,
                 admin: models.AdminUser = Depends(require_admin),
                 db: Session = Depends(get_db)):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="Super Admin ብቻ ነው የሚችለው")
    existing = db.query(models.AdminUser).filter(
        models.AdminUser.telegram_id == req.telegram_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="ይህ Admin አስቀድሞ አለ")
    new_admin = models.AdminUser(
        telegram_id=req.telegram_id, display_name=req.display_name,
        role=req.role, notes=req.notes,
        created_by=admin.telegram_id, is_active=True
    )
    db.add(new_admin)
    log_admin_action(db, admin, "create_admin",
                     target_type="admin", target_id=req.telegram_id,
                     details=f"role={req.role}")
    db.commit()
    return {"message": "Admin ተፈጥሯል", "id": new_admin.id}


@app.get("/api/admin/list")
def list_admins(admin: models.AdminUser = Depends(require_admin),
                db: Session = Depends(get_db)):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="Super Admin ብቻ ነው የሚችለው")
    admins = db.query(models.AdminUser).order_by(models.AdminUser.created_at.desc()).all()
    return {"admins": [{
        "id": a.id, "telegram_id": a.telegram_id,
        "display_name": a.display_name, "role": a.role,
        "is_active": a.is_active, "is_super": a.role == "super_admin",
        "created_at": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "",
        "last_login": a.last_login.strftime("%Y-%m-%d %H:%M") if a.last_login else "ምንም",
        "notes": a.notes or ""
    } for a in admins]}


@app.post("/api/admin/{admin_id}/toggle")
def toggle_admin(admin_id: int,
                 admin: models.AdminUser = Depends(require_admin),
                 db: Session = Depends(get_db)):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="Super Admin ብቻ ነው የሚችለው")
    target = db.query(models.AdminUser).filter(models.AdminUser.id == admin_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Admin አልተገኘም")
    if target.role == "super_admin":
        raise HTTPException(status_code=400, detail="Super Admin ማሰናከል አይቻልም")
    target.is_active = not target.is_active
    log_admin_action(db, admin, "toggle_admin",
                     target_type="admin", target_id=target.telegram_id,
                     details=f"is_active={target.is_active}")
    db.commit()
    return {"message": "ተስተካክሏል", "is_active": target.is_active}


@app.delete("/api/admin/{admin_id}")
def delete_admin(admin_id: int,
                 admin: models.AdminUser = Depends(require_admin),
                 db: Session = Depends(get_db)):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="Super Admin ብቻ ነው የሚችለው")
    target = db.query(models.AdminUser).filter(models.AdminUser.id == admin_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Admin አልተገኘም")
    if target.role == "super_admin":
        raise HTTPException(status_code=400, detail="Super Admin ማጥፋት አይቻልም")
    log_admin_action(db, admin, "delete_admin",
                     target_type="admin", target_id=target.telegram_id)
    db.delete(target)
    db.commit()
    return {"message": "ተሰርዟል"}


# =====================================================================
# ✅ ADMIN: Audit Log
# =====================================================================
@app.get("/api/admin/audit")
def get_audit_log(admin: models.AdminUser = Depends(require_admin),
                  db: Session = Depends(get_db),
                  limit: int = 100):
    if not (is_super_admin(admin) or has_permission(admin, "view_audit")):
        raise HTTPException(status_code=403, detail="ፈቃድ የለዎትም")
    logs = db.query(models.AuditLog).order_by(
        models.AuditLog.created_at.desc()).limit(limit).all()
    return {"logs": [{
        "id": l.id, "actor_id": l.actor_id,
        "actor_username": l.actor_username, "actor_role": l.actor_role,
        "action": l.action, "target_type": l.target_type,
        "target_id": l.target_id, "details": l.details,
        "created_at": l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else ""
    } for l in logs]}


# =====================================================================
# ✅ ADMIN: Recover Game & Reconcile
# =====================================================================
@app.post("/api/admin/recover_game/{game_id}")
def recover_game(game_id: int,
                 admin: models.AdminUser = Depends(require_admin),
                 db: Session = Depends(get_db)):
    require_permission(admin, "control_games")
    game = lock_game(db, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="ጨዋታው አልተገኘም")
    if game.payout_completed:
        return {"message": "ጨዋታው አስቀድሞ ተጠናቋል", "status": game.status}
    if game.status != "playing":
        return {"message": f"ጨዋታው '{game.status}' ሁኔታ ላይ ነው።",
                "payout_completed": False, "recovery_allowed": False,
                "reason": f"invalid_status:{game.status}"}
    payouts = db.query(models.LedgerEntry).filter(
        models.LedgerEntry.entry_type == "prize_payout",
        models.LedgerEntry.reference_type == "game",
        models.LedgerEntry.reference_id == str(game.id)).all()
    if not payouts:
        return {"message": "ምንም የpayout መዝገብ የለም",
                "payout_completed": False, "recovery_allowed": False,
                "reason": "no_payouts"}
    called_set = parse_called_numbers(game.called_numbers)
    if called_set is None:
        return {"message": "⚠️ called_numbers ቅርጸት ትክክል አይደለም",
                "payout_completed": False, "recovery_allowed": False,
                "reason": "invalid_called_numbers"}
    payout_total = sum(Decimal(str(p.amount)) for p in payouts)
    expected_jackpot = Decimal(str(game.original_jackpot or "0.00"))
    if expected_jackpot == Decimal("0.00") and payout_total > Decimal("0.00"):
        expected_jackpot = payout_total
    jackpot_match = payout_total == expected_jackpot
    winner_issues = []
    for p in payouts:
        if Decimal(str(p.amount)) < Decimal("0.00"):
            winner_issues.append({"user_id": p.user_id, "issue": "negative_payout"})
            continue
        card = db.query(models.Card).filter(
            models.Card.user_id == p.user_id, models.Card.game_id == game.id,
            models.Card.refunded == False).first()
        if not card:
            winner_issues.append({"user_id": p.user_id, "issue": "no_card_found"})
            continue
        if not card.is_winner:
            winner_issues.append({"user_id": p.user_id, "issue": "is_winner_flag_false"})
            continue
        try:
            nums = [int(x) for x in card.numbers.split(",")]
        except (ValueError, AttributeError):
            winner_issues.append({"user_id": p.user_id, "issue": "invalid_card_numbers"})
            continue
        is_valid, err = validate_bingo_card(nums)
        if not is_valid:
            winner_issues.append({"user_id": p.user_id, "issue": f"invalid_card:{err}"})
            continue
        if not check_card_winner(nums, called_set):
            winner_issues.append({"user_id": p.user_id, "issue": "not_actual_bingo_winner"})
    balance_issues = []
    unique_user_ids = {p.user_id for p in payouts}
    for uid in unique_user_ids:
        user = db.query(models.User).filter(models.User.id == uid).first()
        if not user:
            balance_issues.append({"user_id": uid, "issue": "user_not_found"})
            continue
        ledger_sum = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
            models.LedgerEntry.user_id == uid).scalar()
        ledger_sum = Decimal(str(ledger_sum or "0.00"))
        if ledger_sum != Decimal(str(user.balance)):
            balance_issues.append({"user_id": user.telegram_id, "issue": "balance_mismatch"})
    refunded_cards = db.query(models.Card).filter(
        models.Card.game_id == game.id, models.Card.refunded == True).count()
    winners_card_count = db.query(models.Card).filter(
        models.Card.game_id == game.id, models.Card.is_winner == True,
        models.Card.refunded == False).count()
    all_checks_pass = (
        jackpot_match and len(winner_issues) == 0 and len(balance_issues) == 0
        and refunded_cards == 0 and winners_card_count == len(payouts)
    )
    if all_checks_pass:
        game.payout_completed = True
        game.status = "finished"
        game.finished_at = datetime.now(timezone.utc)
        game.jackpot = Decimal("0.00")
        if payouts:
            game.winner_id = min(payouts, key=lambda p: p.id).user_id
        log_admin_action(db, admin, "recover_game",
                         target_type="game", target_id=game.id,
                         details=f"total={payout_total}")
        db.commit()
        return {"message": "✅ ጨዋታው በተሳካ ሁኔታ ተጠናቋል",
                "payout_completed": True, "all_checks_pass": True}
    return {"message": "⚠️ ማረጋገጫዎች አልተሟሉም",
            "payout_completed": False, "all_checks_pass": False,
            "winner_issues": winner_issues,
            "balance_issues": balance_issues}


@app.get("/api/admin/reconcile")
def reconcile(admin: models.AdminUser = Depends(require_admin),
              db: Session = Depends(get_db)):
    if not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="Super Admin ብቻ ነው የሚችለው")
    issues = []
    users = db.query(models.User).all()
    balance_mismatches = []
    for u in users:
        ledger_sum = db.query(func.coalesce(func.sum(models.LedgerEntry.amount), 0)).filter(
            models.LedgerEntry.user_id == u.id).scalar()
        ledger_sum = Decimal(str(ledger_sum or "0.00"))
        if ledger_sum != Decimal(str(u.balance)):
            balance_mismatches.append({"user_id": u.telegram_id,
                                       "balance": float(u.balance),
                                       "ledger_sum": float(ledger_sum)})
    if balance_mismatches:
        issues.append({"type": "balance_vs_ledger",
                       "count": len(balance_mismatches),
                       "details": balance_mismatches[:50]})
    duplicate_entries = db.query(
        models.LedgerEntry.user_id, models.LedgerEntry.entry_type,
        models.LedgerEntry.reference_type, models.LedgerEntry.reference_id,
        func.count(models.LedgerEntry.id).label("cnt")
    ).group_by(
        models.LedgerEntry.user_id, models.LedgerEntry.entry_type,
        models.LedgerEntry.reference_type, models.LedgerEntry.reference_id
    ).having(func.count(models.LedgerEntry.id) > 1).all()
    if duplicate_entries:
        issues.append({"type": "duplicate_ledger_entries",
                       "count": len(duplicate_entries),
                       "details": [{"user_id": d.user_id, "entry_type": d.entry_type,
                                    "reference_id": d.reference_id,
                                    "count": d.cnt} for d in duplicate_entries[:50]]})
    return {"checked_users": len(users), "issues_found": len(issues),
            "issues": issues}


# =====================================================================
# ✅ BINGO ENGINE LOOP
# =====================================================================
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
                logger.warning(f"⚠️ Engine DB connection failed: {db_err}")
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
    games = db.query(models.Game).filter(
        models.Game.status == "playing").with_for_update().all()
    for game in games:
        existing_payout = db.query(models.LedgerEntry.id).filter(
            models.LedgerEntry.entry_type == "prize_payout",
            models.LedgerEntry.reference_type == "game",
            models.LedgerEntry.reference_id == str(game.id)).first()
        if existing_payout and not game.payout_completed:
            logger.critical(f"Game {game.id} FROZEN.")
            continue
        if game.last_drawn_at:
            elapsed = (datetime.now(timezone.utc) - game.last_drawn_at).total_seconds()
            if elapsed < DRAW_INTERVAL_SECONDS:
                continue
        called_set = parse_called_numbers(game.called_numbers)
        if called_set is None:
            logger.error(f"Game {game.id} corrupt called_numbers")
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
        models.LedgerEntry.reference_id == str(game.id)).all()
    if existing_payouts:
        logger.critical(f"Game {game.id} existing payouts.")
        return
    cards = db.query(models.Card).filter(
        models.Card.game_id == game.id,
        models.Card.refunded.is_(False)
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
        user.balance = Decimal(str(user.balance)) + amount
        add_ledger(db, user, "prize_payout", amount,
                   ref_type="game", ref_id=game.id,
                   notes=f"payout card {card.id} of game {game.id}")
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


# =====================================================================
# ✅ STARTUP
# =====================================================================
@app.on_event("startup")
def startup_event():
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names(schema="public"))

        # Alembic migration
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

        # Tables check
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names(schema="public"))
        missing_tables = sorted(REQUIRED_TABLES - existing_tables)
        if missing_tables:
            logger.warning(f"⚠️ Missing tables: {missing_tables}")
            Base.metadata.create_all(bind=engine)
            logger.info("✅ create_all completed")

        # Connection test
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("✅ Database connection verified")

        # Super Admin
        db_init = SessionLocal()
        try:
            ensure_super_admin_exists(db_init)
            logger.info("✅ Super Admin verified")
        finally:
            db_init.close()

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
