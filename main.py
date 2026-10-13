"""
=====================================================================
✅ የዳታቤዝ ሞዴሎች (models.py) - v6.5 FINAL
=====================================================================
✅ Numeric(12,2) ለገንዘብ
✅ default= + server_default= (ORM + psql)
✅ CHECK constraints ለ status/entry_type/method
✅ UNIQUE constraints ለድግግሞሽ
✅ Ledger reference ግዴታ
✅ timezone-aware datetimes
✅ Partial unique index — አንድ ንቁ ጨዋታ ብቻ
✅ original_jackpot ለ recover_game ማረጋገጫ
=====================================================================
"""
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, ForeignKey,
    DateTime, Text, UniqueConstraint, Index, CheckConstraint, text
)
from datetime import datetime, timezone
from decimal import Decimal
from database import Base


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    balance = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00")
    )
    is_banned = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false")
    )
    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint('balance >= 0', name='ck_user_balance_non_negative'),
    )


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True)
    status = Column(
        String,
        nullable=False,
        default="waiting",
        server_default=text("'waiting'")
    )
    jackpot = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00")
    )
    # ✅ P0 FIX: የመጀመሪያው jackpot
    original_jackpot = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00")
    )
    card_price = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("10.00"),
        server_default=text("10.00")
    )
    call_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0")
    )
    called_numbers = Column(
        Text,
        nullable=False,
        default="",
        server_default=text("''")
    )
    last_number = Column(Integer, nullable=True)
    last_drawn_at = Column(DateTime(timezone=True), nullable=True)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    refunded = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false")
    )
    payout_completed = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false")
    )
    rollover_jackpot = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00")
    )
    rollover_received = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default=text("0.00")
    )
    rollover_transferred = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false")
    )

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        server_default=text("now()")
    )

    __table_args__ = (
        Index(
            'uq_single_active_game',
            text("(status IN ('waiting','playing'))"),
            unique=True,
            postgresql_where=text("status IN ('waiting','playing')"),
        ),
        CheckConstraint('jackpot >= 0', name='ck_game_jackpot_non_negative'),
        CheckConstraint('original_jackpot >= 0', name='ck_game_original_jackpot_non_negative'),
        CheckConstraint('rollover_jackpot >= 0', name='ck_game_rollover_non_negative'),
        CheckConstraint('rollover_received >= 0', name='ck_game_rollover_recv_non_negative'),
        CheckConstraint('card_price > 0', name='ck_game_card_price_positive'),
        CheckConstraint('call_count >= 0', name='ck_game_call_count_non_negative'),
        CheckConstraint(
            "status IN ('waiting','playing','finished','cancelled')",
            name='ck_game_status_valid'
        ),
    )


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    numbers = Column(Text, nullable=False)
    is_winner = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false")
    )
    price_paid = Column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("10.00"),
        server_default=text("10.00")
    )
    refunded = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false")
    )
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint('user_id', 'game_id', name='uq_user_game_card'),
        CheckConstraint('price_paid > 0', name='ck_card_price_positive'),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    method = Column(String, nullable=False)
    status = Column(
        String,
        nullable=False,
        default="pending",
        server_default=text("'pending'")
    )
    reference = Column(String, unique=True, nullable=False, index=True)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        server_default=text("now()"),
        index=True
    )

    __table_args__ = (
        CheckConstraint('amount > 0', name='ck_transaction_amount_positive'),
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name='ck_transaction_status_valid'
        ),
        CheckConstraint(
            "method IN ('ቴሌብር','ሲቢኢ ብር')",
            name='ck_transaction_method_valid'
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        server_default=text("now()"),
        index=True
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String, nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    reference_type = Column(String, nullable=False)
    reference_id = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        server_default=text("now()"),
        index=True
    )

    __table_args__ = (
        UniqueConstraint(
            'user_id', 'entry_type', 'reference_type', 'reference_id',
            name='uq_ledger_no_duplicate'
        ),
        CheckConstraint(
            "entry_type IN ("
            "'deposit_approved','card_purchase','prize_payout','refund'"
            ")",
            name='ck_ledger_entry_type_valid'
        ),
        CheckConstraint(
            "reference_type IN ('transaction','card','game')",
            name='ck_ledger_reference_type_valid'
        ),
        CheckConstraint('balance_after >= 0', name='ck_ledger_balance_non_negative'),
    )
