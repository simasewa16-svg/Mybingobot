"""
============================================================
 BingoGame - Enterprise Architecture Database (10x Edition)
============================================================
"""

import os
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, SmallInteger,
    String, Text, Boolean, Numeric, Float, DateTime, Date, Time,
    ForeignKey, JSON, Enum, Index, UniqueConstraint, CheckConstraint,
    event, text, func
)
from sqlalchemy.orm import (
    sessionmaker, declarative_base, relationship,
    validates, backref
)

# ============================================================
# 🚨 1. የእርስዎ መረጃዎች (CONFIGURATION) - እዚህ ጋር ብቻ ይቀይሩ 🚨
# ============================================================

# 1. የቴሌግራም ቦት ቶከን (ከ BotFather ያገኘኸው)
BOT_TOKEN = "8962566823:AAHYTr58QBRU85-HkeLb91M_gIOBzaTh7jw" 

# 2. የክፍያ አካውንት ቁጥሮች (ስልክ ቁጥርህን እዚህ አስገባ)
TELEBIRR_PHONE = "0912345678"  # የቴሌብር ስልክ ቁጥርህ
CBE_BIRR_PHONE = "0912345678"  # የCBE ብር ስልክ ቁጥርህ
ADMIN_PHONE = "0912345678"     # የአድሚን ስልክ ቁጥር

# ============================================================
# 2. DATABASE CONFIGURATION & ENGINE
# ============================================================
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./bingobot.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_size=20 if IS_POSTGRES else 10,
    max_overflow=40 if IS_POSTGRES else 20,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=False,
    future=True,
)

if IS_POSTGRES:
    @event.listens_for(engine, "connect")
    def _set_utc(dbapi_conn, _):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")

SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)

Base = declarative_base()

def utc_now():
    return datetime.now(timezone.utc)

def generate_uuid():
    return str(uuid.uuid4())

# ============================================================
# 3. CORE UTILITIES
# ============================================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ ሁሉም ዘመናዊ ሰንጠረዦች በተሳካ ሁኔታ ተፈጥረዋል!")

# ============================================================
# 4. CORE USER & FINANCIAL TABLES
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(64), index=True)
    first_name = Column(String(128))
    last_name = Column(String(128))
    language_code = Column(String(10), default="am")
    phone = Column(String(20), unique=True)
    email = Column(String(128))

    is_banned = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    vip_level = Column(SmallInteger, default=0) 
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)

    referral_code = Column(String(20), unique=True, index=True)
    referred_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    referral_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    version_id = Column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version_id}

    wallets = relationship("Wallet", back_populates="user", cascade="all, delete-orphan")
    cards = relationship("BingoCard", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    tickets = relationship("SupportTicket", back_populates="user")

    __table_args__ = (
        Index("idx_user_active", "is_banned", "is_verified"),
    )


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    currency = Column(String(10), default="ETB")
    
    balance = Column(Numeric(18, 2), default=Decimal("0.00"))
    locked_balance = Column(Numeric(18, 2), default=Decimal("0.00"))
    bonus_balance = Column(Numeric(18, 2), default=Decimal("0.00"))
    referral_balance = Column(Numeric(18, 2), default=Decimal("0.00"))

    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="wallets")

    __table_args__ = (
        UniqueConstraint("user_id", "currency", name="uq_user_currency"),
        CheckConstraint("balance >= 0", name="chk_wallet_balance_positive"),
        CheckConstraint("locked_balance >= 0", name="chk_wallet_locked_positive"),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String(30), nullable=False, index=True) 
    amount = Column(Numeric(18, 2), nullable=False) 
    balance_before = Column(Numeric(18, 2), nullable=False)
    balance_after = Column(Numeric(18, 2), nullable=False)
    
    reference_id = Column(String(64), index=True) 
    hash_signature = Column(String(128)) 
    
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)

    __table_args__ = (
        CheckConstraint("amount != 0", name="chk_ledger_amount_not_zero"),
    )


# ============================================================
# 5. BINGO GAME ENGINE TABLES
# ============================================================

class BingoGame(Base):
    __tablename__ = "bingo_games"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id_str = Column(String(36), default=generate_uuid, unique=True, index=True)
    status = Column(String(20), default="lobby", index=True) 
    game_mode = Column(String(20), default="classic") 
    
    entry_fee = Column(Numeric(18, 2), default=Decimal("20.00"))
    prize_pool = Column(Numeric(18, 2), default=Decimal("0.00"))
    jackpot_allocated = Column(Numeric(18, 2), default=Decimal("0.00"))
    
    max_players = Column(Integer, default=100)
    current_players = Column(Integer, default=0)
    
    called_numbers = Column(JSON, default=list) 
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    cards = relationship("BingoCard", back_populates="game")

    __table_args__ = (
        CheckConstraint("status IN ('lobby', 'playing', 'completed', 'cancelled')", name="chk_game_status"),
        CheckConstraint("entry_fee >= 0", name="chk_game_fee"),
    )


class BingoCard(Base):
    __tablename__ = "bingo_cards"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    game_id = Column(BigInteger, ForeignKey("bingo_games.id"), nullable=False, index=True)
    
    card_data = Column(JSON, nullable=False) 
    marked_data = Column(JSON, default=list) 
    
    is_checked = Column(Boolean, default=False)
    is_winner = Column(Boolean, default=False, index=True)
    win_type = Column(String(30), default="none") 
    
    purchased_at = Column(DateTime(timezone=True), default=utc_now)

    user = relationship("User", back_populates="cards")
    game = relationship("BingoGame", back_populates="cards")

    __table_args__ = (
        Index("idx_card_user_game", "user_id", "game_id"),
    )


# ============================================================
# 6. TRANSACTIONS & SUPPORT
# ============================================================

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    
    payment_gateway = Column(String(30), default="Chapa") 
    transaction_type = Column(String(20), nullable=False, index=True) 
    amount = Column(Numeric(18, 2), nullable=False)
    fee = Column(Numeric(18, 2), default=Decimal("0.00"))
    
    status = Column(String(20), default="initiated", index=True) 
    reference_id = Column(String(64), unique=True, default=generate_uuid)
    gateway_reference = Column(String(128), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="transactions")

    __table_args__ = (
        CheckConstraint("status IN ('initiated', 'processing', 'success', 'failed')", name="chk_tx_status"),
        CheckConstraint("amount > 0", name="chk_tx_amount"),
    )


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    subject = Column(String(256), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(20), default="open", index=True) 
    admin_response = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="tickets")


# ============================================================
# 7. ENGAGEMENT & BONUSES
# ============================================================

class DailyReward(Base):
    __tablename__ = "daily_rewards"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    day_number = Column(Integer, nullable=False)
    reward_amount = Column(Numeric(18, 2), nullable=False)
    claimed_at = Column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index('uq_user_daily_reward', 'user_id', 'day_number', func.date('claimed_at'), unique=True),
        CheckConstraint("day_number BETWEEN 1 AND 7", name="chk_day_number"),
    )


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, index=True)
    bonus_type = Column(String(20)) 
    value = Column(Numeric(18, 2), nullable=False)
    
    min_deposit_required = Column(Numeric(18, 2), default=Decimal("0.00"))
    max_uses = Column(Integer, default=100)
    current_uses = Column(Integer, default=0)
    
    expires_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)


# ============================================================
# 8. AUDIT & SYSTEM LOGGING
# ============================================================

class SystemAuditLog(Base):
    __tablename__ = "system_audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    action_type = Column(String(64), nullable=False, index=True) 
    description = Column(Text, nullable=False)
    severity = Column(String(20), default="info", index=True) 
    ip_address = Column(String(45), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, index=True)


# ============================================================
# 9. INITIALIZATION
# ============================================================
if __name__ == "__main__":
    init_db()
