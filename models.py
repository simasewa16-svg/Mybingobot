"""
=====================================================================
✅ የዳታቤዝ ሞዴሎች (models.py) - v6.3 FINAL
=====================================================================
✅ Numeric(12,2) ለገንዘብ — Float አይደለም
✅ server_default ለገንዘብ አምዶች (psql-safe)
✅ CHECK constraints ለ status/entry_type/method
✅ UNIQUE constraints ለድግግሞሽ
✅ Ledger reference ግዴታ (NULL አይፈቀድም)
✅ timezone-aware datetimes
✅ Partial unique index — አንድ ንቁ ጨዋታ ብቻ
✅ index=True ከ PK ተወግዷል (ድግግሞሽ)

ማስታወሻ፦ 
- LedgerEntry.amount አሉታዊ ሊሆን ይችላል (card_purchase)
- jackpot_rollover ከ entry_type ተወግዷል (main.py አይጠቀመውም)
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
    """✅ timezone-aware UTC datetime"""
    return datetime.now(timezone.utc)


class User(Base):
    """✅ የተጠቃሚ መዝገብ"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=True)
    balance = Column(
        Numeric(12, 2),
        nullable=False,
        server_default=text("0.00")
    )
    is_banned = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        CheckConstraint('balance >= 0', name='ck_user_balance_non_negative'),
    )


class Game(Base):
    """✅ የBingo ጨዋታ ሁኔታ"""
    __tablename__ = "games"

    id = Column(Integer, primary_key=True)
    status = Column(String, default="waiting", nullable=False, server_default=text("'waiting'"))
    jackpot = Column(
        Numeric(12, 2),
        nullable=False,
        server_default=text("0.00")
    )
    card_price = Column(
        Numeric(12, 2),
        nullable=False,
        server_default=text("10.00")
    )
    call_count = Column(Integer, default=0, nullable=False, server_default=text("0"))
    called_numbers = Column(Text, default="", nullable=False, server_default=text("''"))
    last_number = Column(Integer, nullable=True)
    last_drawn_at = Column(DateTime(timezone=True), nullable=True)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    refunded = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    payout_completed = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    rollover_jackpot = Column(
        Numeric(12, 2),
        nullable=False,
        server_default=text("0.00")
    )
    rollover_received = Column(
        Numeric(12, 2),
        nullable=False,
        server_default=text("0.00")
    )
    rollover_transferred = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        # ✅ አንድ ጊዜ ብቻ ንቁ ጨዋታ
        Index(
            'uq_single_active_game',
            text("(status IN ('waiting','playing'))"),
            unique=True,
            postgresql_where=text("status IN ('waiting','playing')"),
        ),
        # ✅ አሉታዊ እሴቶች
        CheckConstraint('jackpot >= 0', name='ck_game_jackpot_non_negative'),
        CheckConstraint('rollover_jackpot >= 0', name='ck_game_rollover_non_negative'),
        CheckConstraint('rollover_received >= 0', name='ck_game_rollover_recv_non_negative'),
        CheckConstraint('card_price > 0', name='ck_game_card_price_positive'),
        CheckConstraint('call_count >= 0', name='ck_game_call_count_non_negative'),
        # ✅ status የተፈቀዱ እሴቶች
        CheckConstraint(
            "status IN ('waiting','playing','finished','cancelled')",
            name='ck_game_status_valid'
        ),
    )


class Card(Base):
    """✅ የተጫዋች የBingo ካርድ"""
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    numbers = Column(Text, nullable=False)
    is_winner = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    price_paid = Column(
        Numeric(12, 2),
        nullable=False,
        server_default=text("10.00")
    )
    refunded = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'game_id', name='uq_user_game_card'),
        CheckConstraint('price_paid > 0', name='ck_card_price_positive'),
    )


class Transaction(Base):
    """✅ የክፍያ ጥያቄ"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    method = Column(String, nullable=False)
    status = Column(String, default="pending", nullable=False, server_default=text("'pending'"))
    reference = Column(String, unique=True, nullable=False, index=True)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

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
    """✅ የAdmin ድርጊቶች ማህደር"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class LedgerEntry(Base):
    """
    ✅ የገንዘብ መዝገብ
    entry_type (4 ብቻ — main.py የሚጠቀማቸው):
      - deposit_approved : ገንዘብ ገቢ
      - card_purchase    : ካርድ ግዢ (አሉታዊ)
      - prize_payout     : ሽልማት ክፍያ
      - refund           : ገንዘብ መመለስ

    ማስታወሻ፦ amount አሉታዊ ሊሆን ይችላል (card_purchase)
    """
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String, nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    reference_type = Column(String, nullable=False)
    reference_id = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            'user_id', 'entry_type', 'reference_type', 'reference_id',
            name='uq_ledger_no_duplicate'
        ),
        # ✅ entry_type — jackpot_rollover ተወግዷል
        CheckConstraint(
            "entry_type IN ("
            "'deposit_approved','card_purchase','prize_payout','refund'"
            ")",
            name='ck_ledger_entry_type_valid'
        ),
        # ✅ reference_type የተፈቀዱ እሴቶች
        CheckConstraint(
            "reference_type IN ('transaction','card','game')",
            name='ck_ledger_reference_type_valid'
        ),
        CheckConstraint('balance_after >= 0', name='ck_ledger_balance_non_negative'),
    )
