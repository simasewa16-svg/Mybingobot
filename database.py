"""
============================================================
 BingoGame - Complete Database Module
 Author: Maker & Checker Architecture
 Version: 100x Extended Edition
 Tables: 55+ | Indexes: 80+ | Constraints: 60+
============================================================
"""

import os
import uuid
from datetime import datetime, date, timedelta
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
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.dialects.postgresql import JSONB

# ============================================================
# 1. DATABASE URL & ENGINE
# ============================================================
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./bingobot.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_size=10 if IS_POSTGRES else 5,
    max_overflow=20 if IS_POSTGRES else 10,
    pool_pre_ping=True,
    pool_recycle=60,
    echo=False,
    future=True,
)

# UTC timezone listener
if IS_POSTGRES:
    @event.listens_for(engine, "connect")
    def _set_utc(dbapi_conn, _):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")

SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
)

Base = declarative_base()


# ============================================================
# 2. HELPER FUNCTIONS
# ============================================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ ሁሉም ሠንጠረዦች ተፈጥረዋል")


def drop_all():
    Base.metadata.drop_all(bind=engine)
    print("⚠️ ሁሉም ሠንጠረዦች ተጠፍተዋል")


def get_db_status():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "connected", "type": "postgres" if IS_POSTGRES else "sqlite"}
    except Exception as e:
        return {"status": "disconnected", "error": str(e)[:100]}


def generate_uuid():
    return str(uuid.uuid4())


# ============================================================
# 3. CORE TABLES
# ============================================================

class User(Base):
    __tablename__ = "users"

    # Identity
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(64))
    first_name = Column(String(128))
    last_name = Column(String(128))
    language_code = Column(String(10), default="am")
    phone = Column(String(20))
    email = Column(String(128))

    # Money
    balance = Column(Numeric(18, 2), default=Decimal("0.00"))
    locked_balance = Column(Numeric(18, 2), default=Decimal("0.00"))
    bonus_balance = Column(Numeric(18, 2), default=Decimal("0.00"))
    total_deposited = Column(Numeric(18, 2), default=Decimal("0.00"))
    total_withdrawn = Column(Numeric(18, 2), default=Decimal("0.00"))
    total_wagered = Column(Numeric(18, 2), default=Decimal("0.00"))
    total_won = Column(Numeric(18, 2), default=Decimal("0.00"))
    currency = Column(String(10), default="ETB")

    # Status
    is_banned = Column(Boolean, default=False)
    is_flagged = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_vip = Column(Boolean, default=False)
    vip_tier = Column(SmallInteger, default=0)
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)

    # Stats
    total_wins = Column(Integer, default=0)
    total_losses = Column(Integer, default=0)
    total_games = Column(Integer, default=0)
    total_cards_bought = Column(Integer, default=0)
    current_streak = Column(Integer, default=0)
    max_streak = Column(Integer, default=0)

    # Referral
    referral_code = Column(String(20), unique=True, index=True)
    referred_by = Column(BigInteger, ForeignKey("users.id"))
    referral_count = Column(Integer, default=0)
    referral_earnings = Column(Numeric(18, 2), default=Decimal("0.00"))

    # KYC
    kyc_status = Column(String(20), default="none")
    kyc_level = Column(SmallInteger, default=0)
    kyc_submitted_at = Column(DateTime)
    kyc_verified_at = Column(DateTime)

    # Security
    two_factor_enabled = Column(Boolean, default=False)
    last_login_ip = Column(String(45))
    last_login_device = Column(String(128))
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime)

    # Preferences
    notifications_enabled = Column(Boolean, default=True)
    sound_enabled = Column(Boolean, default=True)
    haptic_enabled = Column(Boolean, default=True)
    theme = Column(String(20), default="dark")

    # Meta
    notes = Column(Text)
    tags = Column(JSON, default=list)
    extra_data = Column(JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_active = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime)

    # Relationships
    cards = relationship("Card", back_populates="user", lazy="dynamic")
    transactions = relationship("Transaction", back_populates="user", lazy="dynamic")
    ledger_entries = relationship("LedgerEntry", back_populates="user", lazy="dynamic")

    __table_args__ = (
        CheckConstraint("balance >= 0", name="chk_user_balance"),
        CheckConstraint("bonus_balance >= 0", name="chk_user_bonus"),
        CheckConstraint("locked_balance >= 0", name="chk_user_locked"),
        CheckConstraint("vip_tier >= 0 AND vip_tier <= 5", name="chk_vip_tier"),
        CheckConstraint("level >= 1", name="chk_user_level"),
        CheckConstraint("kyc_status IN ('none','pending','approved','rejected')",
                        name="chk_kyc_status"),
        Index("idx_users_active", "is_active", "last_active"),
        Index("idx_users_vip", "vip_tier"),
        Index("idx_users_balance", "balance"),
    )

    @hybrid_property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip()

    @hybrid_property
    def total_balance(self):
        return self.balance + self.bonus_balance

    @validates("balance")
    def validate_balance(self, key, value):
        if value is not None and value < 0:
            raise ValueError("Balance cannot be negative")
        return value


class Game(Base):
    __tablename__ = "games"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_code = Column(String(20), unique=True, index=True)
    status = Column(String(20), default="waiting", index=True)
    game_type = Column(String(20), default="75ball")
    pattern = Column(String(30), default="line")  # line/2line/full/house

    # Money
    jackpot = Column(Numeric(18, 2), default=Decimal("0.00"))
    original_jackpot = Column(Numeric(18, 2), default=Decimal("0.00"))
    rollover_jackpot = Column(Numeric(18, 2), default=Decimal("0.00"))
    rollover_received = Column(Numeric(18, 2), default=Decimal("0.00"))
    rollover_transferred = Column(Numeric(18, 2), default=Decimal("0.00"))
    card_price = Column(Numeric(10, 2), default=Decimal("10.00"))
    rake_percentage = Column(Float, default=10.0)

    # Game state
    call_count = Column(Integer, default=0)
    called_numbers = Column(JSON, default=list)
    last_number = Column(Integer)
    min_players = Column(Integer, default=2)
    max_players = Column(Integer, default=100)
    current_players = Column(Integer, default=0)
    current_cards = Column(Integer, default=0)

    # Winner
    winner_id = Column(BigInteger, ForeignKey("users.id"))
    winning_card_id = Column(BigInteger, ForeignKey("cards.id"))
    win_pattern = Column(String(30))
    win_amount = Column(Numeric(18, 2))
    payout_completed = Column(Boolean, default=False)
    refunded = Column(Boolean, default=False)

    # Config
    draw_interval = Column(Integer, default=3)
    waiting_timeout = Column(Integer, default=60)
    auto_start = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    last_drawn_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cards = relationship("Card", back_populates="game", lazy="dynamic")

    __table_args__ = (
        CheckConstraint("status IN ('waiting','playing','finished','cancelled')",
                        name="chk_game_status"),
        CheckConstraint("game_type IN ('75ball','80ball','90ball')",
                        name="chk_game_type"),
        CheckConstraint("jackpot >= 0", name="chk_jackpot"),
        CheckConstraint("card_price > 0", name="chk_card_price"),
        Index("idx_games_status_created", "status", "created_at"),
    )


class Card(Base):
    __tablename__ = "cards"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    game_id = Column(BigInteger, ForeignKey("games.id"), nullable=False, index=True)

    numbers = Column(JSON, nullable=False)  # 5x5 grid
    marked_numbers = Column(JSON, default=list)
    marked_count = Column(Integer, default=0)
    price_paid = Column(Numeric(10, 2), default=Decimal("0.00"))

    is_winner = Column(Boolean, default=False, index=True)
    is_auto_daub = Column(Boolean, default=False)
    refunded = Column(Boolean, default=False)
    refunded_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="cards")
    game = relationship("Game", back_populates="cards")

    __table_args__ = (
        Index("idx_cards_user_game", "user_id", "game_id"),
        Index("idx_cards_winner", "game_id", "is_winner"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    fee = Column(Numeric(10, 2), default=Decimal("0.00"))
    net_amount = Column(Numeric(18, 2))
    type = Column(String(20), nullable=False, index=True)
    method = Column(String(30))
    reference = Column(String(128), unique=True, index=True)
    external_ref = Column(String(128))
    status = Column(String(20), default="pending", index=True)
    idempotency_key = Column(String(64), unique=True)

    reviewed_by = Column(BigInteger, ForeignKey("admin_users.id"))
    reviewed_at = Column(DateTime)
    notes = Column(Text)
    metadata_json = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="transactions")

    __table_args__ = (
        CheckConstraint("amount != 0", name="chk_tx_amount"),
        CheckConstraint(
            "type IN ('deposit','withdrawal','bet','win','refund','bonus','fee','jackpot','adjustment')",
            name="chk_tx_type"
        ),
        CheckConstraint(
            "status IN ('pending','completed','failed','cancelled')",
            name="chk_tx_status"
        ),
        Index("idx_tx_user_date", "user_id", "created_at"),
        Index("idx_tx_pending", "status"),
    )


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    fee = Column(Numeric(10, 2), default=Decimal("0.00"))
    net_amount = Column(Numeric(18, 2), nullable=False)
    method = Column(String(30), nullable=False)
    account_number = Column(String(64), nullable=False)
    account_name = Column(String(128), nullable=False)
    bank_code = Column(String(20))
    status = Column(String(20), default="pending", index=True)
    reference = Column(String(128), unique=True)
    idempotency_key = Column(String(64), unique=True)

    reviewed_by = Column(BigInteger, ForeignKey("admin_users.id"))
    reviewed_at = Column(DateTime)
    paid_at = Column(DateTime)
    notes = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_wd_amount"),
        CheckConstraint("net_amount > 0", name="chk_wd_net"),
        CheckConstraint(
            "status IN ('pending','approved','rejected','paid','cancelled')",
            name="chk_wd_status"
        ),
        Index("idx_wd_user_date", "user_id", "created_at"),
        Index("idx_wd_pending", "status"),
    )


class LedgerEntry(Base):
    """Immutable double-entry ledger"""
    __tablename__ = "ledger_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String(30), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    balance_before = Column(Numeric(18, 2))
    balance_after = Column(Numeric(18, 2), nullable=False)
    reference_type = Column(String(30))
    reference_id = Column(BigInteger)
    reference_idempotency = Column(String(64), unique=True)
    notes = Column(Text)
    hash_chain = Column(String(64))  # For tamper detection
    previous_hash = Column(String(64))

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="ledger_entries")

    __table_args__ = (
        CheckConstraint("amount != 0", name="chk_ledger_amount"),
        CheckConstraint("balance_after >= 0", name="chk_ledger_balance"),
        CheckConstraint(
            "entry_type IN ('deposit','withdrawal','bet','win','refund','bonus','fee','rake','jackpot','rollover','adjustment')",
            name="chk_ledger_type"
        ),
        Index("idx_ledger_user_date", "user_id", "created_at"),
    )


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text)
    value_type = Column(String(20), default="string")
    description = Column(Text)
    category = Column(String(30), default="general", index=True)
    is_public = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(BigInteger)

    def __repr__(self):
        return f"<Setting {self.key}={self.value}>"


# ============================================================
# 4. ADMIN & SECURITY
# ============================================================

class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(64))
    display_name = Column(String(128))
    role = Column(String(20), default="moderator", index=True)
    permissions = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    created_by = Column(BigInteger)
    last_login = Column(DateTime)
    last_login_ip = Column(String(45))
    two_factor_enabled = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "role IN ('super','admin','moderator','support','finance')",
            name="chk_admin_role"
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_id = Column(BigInteger, index=True)
    actor_username = Column(String(64))
    actor_role = Column(String(30))
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(30))
    target_id = Column(BigInteger)
    details = Column(JSON, default=dict)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_audit_actor_date", "actor_id", "created_at"),
        Index("idx_audit_target", "target_type", "target_id"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, index=True)
    refresh_token_hash = Column(String(128))
    device_info = Column(JSON, default=dict)
    ip_address = Column(String(45))
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FraudFlag(Base):
    __tablename__ = "fraud_flags"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    flag_type = Column(String(30), nullable=False, index=True)
    severity = Column(String(10), default="low", index=True)
    score = Column(Integer, default=0)
    details = Column(JSON, default=dict)
    is_resolved = Column(Boolean, default=False, index=True)
    resolved_by = Column(BigInteger, ForeignKey("admin_users.id"))
    resolved_at = Column(DateTime)
    resolution_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low','medium','high','critical')",
            name="chk_fraud_severity"
        ),
    )


class PlayerNote(Base):
    __tablename__ = "player_notes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    author_id = Column(BigInteger, nullable=False)
    author_name = Column(String(64))
    note = Column(Text, nullable=False)
    is_warning = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# ============================================================
# 5. GAME EXTENDED
# ============================================================

class GameRound(Base):
    __tablename__ = "game_rounds"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id = Column(BigInteger, ForeignKey("games.id"), nullable=False, index=True)
    round_number = Column(Integer, nullable=False)
    drawn_number = Column(Integer, nullable=False)
    drawn_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("game_id", "drawn_number", name="uq_game_round_number"),
        CheckConstraint("drawn_number BETWEEN 1 AND 90", name="chk_drawn_number"),
    )


class GameHistory(Base):
    __tablename__ = "game_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id = Column(BigInteger, ForeignKey("games.id"), nullable=False, index=True)
    total_players = Column(Integer, default=0)
    total_cards = Column(Integer, default=0)
    total_pot = Column(Numeric(18, 2), default=Decimal("0.00"))
    rake_collected = Column(Numeric(18, 2), default=Decimal("0.00"))
    winner_id = Column(BigInteger, ForeignKey("users.id"))
    winning_card_id = Column(BigInteger, ForeignKey("cards.id"))
    win_pattern = Column(String(30))
    ended_at = Column(DateTime, default=datetime.utcnow, index=True)


class CalledNumberLog(Base):
    __tablename__ = "called_numbers_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id = Column(BigInteger, ForeignKey("games.id"), nullable=False, index=True)
    number = Column(Integer, nullable=False)
    sequence_order = Column(Integer, nullable=False)
    called_at = Column(DateTime, default=datetime.utcnow)


class WinningCombination(Base):
    __tablename__ = "winning_combinations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    pattern_matrix = Column(JSON, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)


class GameTemplate(Base):
    __tablename__ = "game_templates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    game_type = Column(String(20), default="75ball")
    pattern_rules = Column(JSON, nullable=False)
    default_card_price = Column(Numeric(10, 2), default=Decimal("10.00"))
    default_draw_interval = Column(Integer, default=3)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 6. PAYMENT EXTENDED
# ============================================================

class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(30), nullable=False)
    account_number = Column(String(64), nullable=False)
    account_name = Column(String(128), nullable=False)
    is_default = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Deposit(Base):
    __tablename__ = "deposits"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    fee = Column(Numeric(10, 2), default=Decimal("0.00"))
    net_amount = Column(Numeric(18, 2))
    method = Column(String(30), nullable=False)
    reference = Column(String(128), unique=True)
    status = Column(String(20), default="pending", index=True)
    approved_by = Column(BigInteger, ForeignKey("admin_users.id"))
    approved_at = Column(DateTime)
    idempotency_key = Column(String(64), unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_dep_amount"),
    )


class PaymentWebhook(Base):
    __tablename__ = "payment_webhooks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(String(30), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    signature = Column(String(255))
    is_verified = Column(Boolean, default=False, index=True)
    is_processed = Column(Boolean, default=False, index=True)
    processed_at = Column(DateTime)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    from_currency = Column(String(10), nullable=False)
    to_currency = Column(String(10), nullable=False)
    rate = Column(Numeric(18, 6), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("from_currency", "to_currency", name="uq_exchange_pair"),
    )


class Currency(Base):
    __tablename__ = "currencies"

    code = Column(String(10), primary_key=True)
    name = Column(String(50), nullable=False)
    symbol = Column(String(10))
    is_active = Column(Boolean, default=True)
    is_crypto = Column(Boolean, default=False)
    decimals = Column(Integer, default=2)


class WalletBalance(Base):
    __tablename__ = "wallet_balances"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    currency = Column(String(10), nullable=False)
    balance = Column(Numeric(18, 2), default=Decimal("0.00"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "currency", name="uq_wallet_user_currency"),
        CheckConstraint("balance >= 0", name="chk_wallet_balance"),
    )


# ============================================================
# 7. SOCIAL
# ============================================================

class Friend(Base):
    __tablename__ = "friends"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    friend_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "friend_id", name="uq_user_friend"),
    )


class FriendRequest(Base):
    __tablename__ = "friend_requests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sender_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    receiver_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    responded_at = Column(DateTime)

    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','rejected','cancelled')",
                        name="chk_fr_status"),
    )


class Block(Base):
    __tablename__ = "blocks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    blocked_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "blocked_id", name="uq_user_blocked"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id = Column(BigInteger, ForeignKey("games.id"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    message = Column(Text, nullable=False)
    is_deleted = Column(Boolean, default=False)
    is_flagged = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Reaction(Base):
    __tablename__ = "reactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id = Column(BigInteger, ForeignKey("games.id"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    emoji = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 8. ENGAGEMENT
# ============================================================

class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    title = Column(String(100), nullable=False)
    description = Column(Text)
    icon = Column(String(20))
    category = Column(String(30))
    reward_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    reward_xp = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    achievement_id = Column(BigInteger, ForeignKey("achievements.id"), nullable=False)
    progress = Column(Integer, default=0)
    is_completed = Column(Boolean, default=False)
    achieved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),
    )



    


class Streak(Base):
    __tablename__ = "streaks"

    id = Column(BigInteger, p
    total_days = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    referrer_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    referred_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    bonus_paid = Column(Boolean, default=False)
    bonus_amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# ============================================================
# 9. VIP & LEADERBOARD
# ============================================================

class VIPTier(Base):
    __tablename__ = "vip_tiers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tier_level = Column(Integer, unique=True, nullable=False)
    name = Column(String(50), nullable=False)
    required_xp = Column(Integer, nullable=False)
    required_deposits = Column(Numeric(18, 2), default=Decimal("0.00"))
    cashback_percentage = Column(Float, default=0.0)
    withdrawal_fee = Column(Float, default=2.0)
    daily_bonus = Column(Numeric(18, 2), default=Decimal("0.00"))
    benefits = Column(JSON, default=list)


class UserVIP(Base):
    __tablename__ = "user_vip"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    tier_id = Column(BigInteger, ForeignKey("vip_tiers.id"), nullable=False)
    total_deposits = Column(Numeric(18, 2), default=Decimal("0.00"))
    total_wagered = Column(Numeric(18, 2), default=Decimal("0.00"))
    cashback_earned = Column(Numeric(18, 2), default=Decimal("0.00"))
    expires_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LeaderboardSnapshot(Base):
    __tablename__ = "leaderboard_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    period_type = Column(String(20), nullable=False)
    period_key = Column(String(20), nullable=False)
    category = Column(String(30), default="wins")
    rank_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_lb_period", "period_type", "period_key", "category"),
    )


# ============================================================
# 10. MARKETING
# ============================================================

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text)
    discount_amount = Column(Numeric(18, 2))
    discount_percentage = Column(Float)
    bonus_amount = Column(Numeric(18, 2))
    usage_limit = Column(Integer)
    usage_count = Column(Integer, default=0)
    per_user_limit = Column(Integer, default=1)
    min_deposit = Column(Numeric(18, 2))
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Coupon(Base):
    __tablename__ = "coupons"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    code_id = Column(BigInteger, ForeignKey("promo_codes.id"), nullable=False)
    is_used = Column(Boolean, default=False)
    used_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class Bonus(Base):
    __tablename__ = "bonuses"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    bonus_type = Column(String(30), default="fixed")
    amount = Column(Numeric(18, 2), default=Decimal("0.00"))
    percentage = Column(Float, default=0.0)
    max_amount = Column(Numeric(18, 2))
    wagering_requirement = Column(Numeric(18, 2), default=Decimal("0.00"))
    is_active = Column(Boolean, default=True)


class BonusGrant(Base):
    __tablename__ = "bonus_grants"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    bonus_id = Column(BigInteger, ForeignKey("bonuses.id"), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    wagered = Column(Numeric(18, 2), default=Decimal("0.00"))
    status = Column(String(20), default="active")
    expires_at = Column(DateTime)
    granted_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    campaign_type = Column(String(30))
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    target_segment = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 11. ANALYTICS
# ============================================================

class UserEvent(Base):
    __tablename__ = "user_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), index=True)
    event_name = Column(String(64), nullable=False, index=True)
    properties = Column(JSON, default=dict)
    session_id = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_events_name_date", "event_name", "created_at"),
    )


class GameAnalytics(Base):
    __tablename__ = "game_analytics"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    game_id = Column(BigInteger, ForeignKey("games.id"), nullable=False)
    metrics_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class RetentionCohort(Base):
    __tablename__ = "retention_cohorts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cohort_date = Column(Date, nullable=False, index=True)
    day_number = Column(Integer, nullable=False)
    total_users = Column(Integer, default=0)
    retained_users = Column(Integer, default=0)
    retention_rate = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("cohort_date", "day_number", name="uq_cohort_day"),
    )


class DailyStat(Base):
    __tablename__ = "daily_stats"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    stat_date = Column(Date, unique=True, nullable=False, index=True)
    active_users = Column(Integer, default=0)
    new_users = Column(Integer, default=0)
    total_revenue = Column(Numeric(18, 2), default=Decimal("0.00"))
    total_payouts = Column(Numeric(18, 2), default=Decimal("0.00"))
    total_bets = Column(Numeric(18, 2), default=Decimal("0.00"))
    games_played = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================
# 12. LOCALIZATION & KYC
# ============================================================

class Translation(Base):
    __tablename__ = "translations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    language_code = Column(String(10), nullable=False, index=True)
    translation_key = Column(String(100), nullable=False)
    translation_value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("language_code", "translation_key", name="uq_translation"),
    )


class KYCDocument(Base):
    __tablename__ = "kyc_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    doc_type = Column(String(30), nullable=False)
    file_url = Column(Text, nullable=False)
    doc_number = Column(String(64))
    status = Column(String(20), default="pending", index=True)
    reviewed_by = Column(BigInteger, ForeignKey("admin_users.id"))
    reviewed_at = Column(DateTime)
    rejection_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class SelfExclusion(Base):
    __tablename__ = "self_exclusions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(Text)
    duration_days = Column(Integer)
    expires_at = Column(DateTime, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 13. NOTIFICATIONS
# ============================================================

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(30), nullable=False, index=True)
    title = Column(String(128))
    body = Column(Text)
    data = Column(JSON, default=dict)
    priority = Column(String(10), default="normal")
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime)
    sent_via = Column(String(20))
    sent_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_notif_user_unread", "user_id", "is_read"),
    )


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    channel = Column(String(20), nullable=False)
    title_template = Column(String(200))
    content = Column(Text, nullable=False)
    variables = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    push_enabled = Column(Boolean, default=True)
    email_enabled = Column(Boolean, default=False)
    sms_enabled = Column(Boolean, default=False)
    categories = Column(JSON, default=dict)
    quiet_hours_start = Column(Time)
    quiet_hours_end = Column(Time)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================
# 14. SUPPORT
# ============================================================

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    subject = Column(String(150), nullable=False)
    category = Column(String(30))
    priority = Column(String(10), default="normal")
    status = Column(String(20), default="open", index=True)
    assigned_to = Column(BigInteger, ForeignKey("admin_users.id"))
    closed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id = Column(BigInteger, ForeignKey("support_tickets.id"), nullable=False, index=True)
    sender_id = Column(BigInteger, nullable=False)
    sender_type = Column(String(20), default="user")
    message = Column(Text, nullable=False)
    attachment_url = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============================================================
# 15. DEVICES & SECURITY
# ============================================================

class UserDevice(Base):
    __tablename__ = "user_devices"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    device_hash = Column(String(128), nullable=False, index=True)
    device_info = Column(JSON, default=dict)
    is_trusted = Column(Boolean, default=True)
    last_seen = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "device_hash", name="uq_user_device"),
    )


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), index=True)
    ip_address = Column(String(45), index=True)
    user_agent = Column(Text)
    success = Column(Boolean, default=False)
    failure_reason = Column(String(100))
    attempted_at = Column(DateTime, default=datetime.utcnow, index=True)


# ============================================================
# 16. EXPORTS
# ============================================================
__all__ = [
    # Engine
    "engine", "SessionLocal", "Base", "get_db", "init_db", "drop_all",
    "get_db_status", "generate_uuid",
    # Core
    "User", "Game", "Card", "Transaction", "Withdrawal", "LedgerEntry", "Setting",
    # Security
    "AdminUser", "AuditLog", "Session", "FraudFlag", "PlayerNote",
    # Game extended
    "GameRound", "GameHistory", "CalledNumberLog", "WinningCombination", "GameTemplate",
    # Payment
    "PaymentMethod", "Deposit", "PaymentWebhook", "ExchangeRate", "Currency", "WalletBalance",
    # Social
    "Friend", "FriendRequest", "Block", "ChatMessage", "Reaction",
    # Engagement
    "Achievement", "UserAchievement", "DailyReward", "Streak", "Referral",
    # VIP
    "VIPTier", "UserVIP", "LeaderboardSnapshot",
    # Marketing
    "PromoCode", "Coupon", "Bonus", "BonusGrant", "Campaign",
    # Analytics
    "UserEvent", "GameAnalytics", "RetentionCohort", "DailyStat",
    # i18n/KYC
    "Translation", "KYCDocument", "SelfExclusion",
    # Notifications
    "Notification", "NotificationTemplate", "NotificationPreference",
    # Support
    "SupportTicket", "SupportMessage",
    # Devices
    "UserDevice", "LoginAttempt",
]


# ============================================================
# 17. INITIALIZE
# ============================================================
if __name__ == "__main__":
    init_db()
