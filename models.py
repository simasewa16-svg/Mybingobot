"""
=====================================================================
✅ የBingo ጨዋታ ዳታቤዝ ሞዴሎች (models.py) - v7.1 FULL
=====================================================================
✅ አዲስ: original_jackpot, rollover_jackpot, rollover_received, 
         rollover_transferred columns ተጨምረዋል
✅ አዲስ: call_count, called_numbers, last_number ተጨምረዋል
✅ አዲስ: started_at, finished_at, last_drawn_at ተጨምረዋል
=====================================================================
"""
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, DateTime,
    ForeignKey, Text, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timezone
from database import Base


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(50), unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    balance = Column(Numeric(12, 2), nullable=False, default=0.00)
    is_banned = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    cards = relationship("Card", back_populates="user", foreign_keys="Card.user_id")
    transactions = relationship("Transaction", back_populates="user")
    ledger_entries = relationship("LedgerEntry", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, balance={self.balance})>"


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(20), nullable=False, default="waiting", index=True)
    # status values: waiting, playing, finished, cancelled

    # ገንዘብ ተዛማጅ አምዶች
    jackpot = Column(Numeric(12, 2), nullable=False, default=0.00)
    original_jackpot = Column(Numeric(12, 2), nullable=False, default=0.00)
    rollover_jackpot = Column(Numeric(12, 2), nullable=False, default=0.00)
    rollover_received = Column(Numeric(12, 2), nullable=False, default=0.00)
    rollover_transferred = Column(Boolean, nullable=False, default=False)
    card_price = Column(Numeric(10, 2), nullable=False, default=10.00)

    # የጨዋታ ሁኔታ አምዶች
    call_count = Column(Integer, nullable=False, default=0)
    called_numbers = Column(Text, nullable=True, default="")
    last_number = Column(Integer, nullable=True)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # የጊዜ አምዶች
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    last_drawn_at = Column(DateTime(timezone=True), nullable=True)

    # ሁኔታ አምዶች
    payout_completed = Column(Boolean, nullable=False, default=False)
    refunded = Column(Boolean, nullable=False, default=False)

    # Relationships
    cards = relationship("Card", back_populates="game", foreign_keys="Card.game_id")

    def __repr__(self):
        return f"<Game(id={self.id}, status={self.status}, jackpot={self.jackpot})>"


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    numbers = Column(String(255), nullable=False)  # "1,2,3,...,0,..." (25 ቁጥሮች)
    price_paid = Column(Numeric(10, 2), nullable=False, default=10.00)
    is_winner = Column(Boolean, nullable=False, default=False)
    refunded = Column(Boolean, nullable=False, default=False)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Relationships
    user = relationship("User", back_populates="cards", foreign_keys=[user_id])
    game = relationship("Game", back_populates="cards", foreign_keys=[game_id])

    # አንድ ተጠቃሚ በአንድ ጨዋታ አንድ ካርድ ብቻ
    __table_args__ = (
        UniqueConstraint("user_id", "game_id", name="uq_card_user_game"),
    )

    def __repr__(self):
        return f"<Card(id={self.id}, user_id={self.user_id}, game_id={self.game_id})>"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    method = Column(String(50), nullable=False)  # ቴሌብር, ሲቢኢ ብር
    reference = Column(String(100), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    # status values: pending, approved, rejected
    reviewed_by = Column(String(50), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    # Relationships
    user = relationship("User", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction(id={self.id}, user_id={self.user_id}, amount={self.amount}, status={self.status})>"


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String(50), nullable=False, index=True)
    # entry_type values: deposit_approved, card_purchase, refund, prize_payout
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    reference_type = Column(String(50), nullable=True)  # card, transaction, game
    reference_id = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    # Relationships
    user = relationship("User", back_populates="ledger_entries")

    # አንድ የማጣቀሻ (reference) አንድ ጊዜ ብቻ እንዲመዘገብ
    __table_args__ = (
        UniqueConstraint(
            "user_id", "entry_type", "reference_type", "reference_id",
            name="uq_ledger_user_type_ref"
        ),
    )

    def __repr__(self):
        return f"<LedgerEntry(id={self.id}, user_id={self.user_id}, type={self.entry_type}, amount={self.amount})>"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(String(50), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50), nullable=True)
    target_id = Column(String(50), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, actor={self.actor_id})>"
