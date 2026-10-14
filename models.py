"""
=====================================================================
✅ የBingo ጨዋታ ዳታቤዝ ሞዴሎች (models.py) - v8.1 FULL SYSTEM
=====================================================================
✅ User, Game, Card, Transaction, LedgerEntry, AuditLog
✅ አዲስ: AdminUser (ብዙ አስተዳዳሪዎች)
✅ አዲስ: Withdrawal (ገንዘብ ማውጣት)
✅ አዲስ: PlayerNote (የAdmin ማስታወሻዎች)
✅ አዲስ: FraudFlag (የማጭበርበር ምልክቶች)
✅ አዲስ: User - first_name, last_name, is_flagged, notes, last_active
✅ አዲስ: Transaction - notes
✅ አዲስ: AuditLog - actor_username, actor_role, ip_address
✅ አዲስ: LedgerEntry - reference_type/id NOT NULL (migration ጋር ይጣጣማል)
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
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    balance = Column(Numeric(12, 2), nullable=False, default=0.00)
    is_banned = Column(Boolean, nullable=False, default=False)
    is_flagged = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_active = Column(DateTime(timezone=True), nullable=True)

    cards = relationship("Card", back_populates="user", foreign_keys="Card.user_id")
    transactions = relationship("Transaction", back_populates="user")
    ledger_entries = relationship("LedgerEntry", back_populates="user")
    withdrawals = relationship("Withdrawal", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, balance={self.balance})>"


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(20), nullable=False, default="waiting", index=True)
    jackpot = Column(Numeric(12, 2), nullable=False, default=0.00)
    original_jackpot = Column(Numeric(12, 2), nullable=False, default=0.00)
    rollover_jackpot = Column(Numeric(12, 2), nullable=False, default=0.00)
    rollover_received = Column(Numeric(12, 2), nullable=False, default=0.00)
    rollover_transferred = Column(Boolean, nullable=False, default=False)
    card_price = Column(Numeric(10, 2), nullable=False, default=10.00)
    call_count = Column(Integer, nullable=False, default=0)
    called_numbers = Column(Text, nullable=True, default="")
    last_number = Column(Integer, nullable=True)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    last_drawn_at = Column(DateTime(timezone=True), nullable=True)
    payout_completed = Column(Boolean, nullable=False, default=False)
    refunded = Column(Boolean, nullable=False, default=False)
    is_test_game = Column(Boolean, nullable=False, default=False)

    cards = relationship("Card", back_populates="game", foreign_keys="Card.game_id")

    def __repr__(self):
        return f"<Game(id={self.id}, status={self.status}, jackpot={self.jackpot})>"


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    numbers = Column(String(255), nullable=False)
    price_paid = Column(Numeric(10, 2), nullable=False, default=10.00)
    is_winner = Column(Boolean, nullable=False, default=False)
    refunded = Column(Boolean, nullable=False, default=False)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    user = relationship("User", back_populates="cards", foreign_keys=[user_id])
    game = relationship("Game", back_populates="cards", foreign_keys=[game_id])

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
    method = Column(String(50), nullable=False)
    reference = Column(String(100), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    reviewed_by = Column(String(50), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    user = relationship("User", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction(id={self.id}, user_id={self.user_id}, amount={self.amount}, status={self.status})>"


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    method = Column(String(50), nullable=False)
    account_number = Column(String(100), nullable=False)
    account_name = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    reference = Column(String(100), nullable=True)
    reviewed_by = Column(String(50), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    user = relationship("User", back_populates="withdrawals")

    def __repr__(self):
        return f"<Withdrawal(id={self.id}, user_id={self.user_id}, amount={self.amount}, status={self.status})>"


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String(50), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    # ✅ NOT NULL — migration 002_v6_5_schema ጋር ይጣጣማል
    reference_type = Column(String(50), nullable=False, default="system")
    reference_id = Column(String(50), nullable=False, default="auto")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    user = relationship("User", back_populates="ledger_entries")

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
    actor_username = Column(String(255), nullable=True)
    actor_role = Column(String(20), nullable=True)
    action = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50), nullable=True)
    target_id = Column(String(50), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, actor={self.actor_id})>"


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(50), unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="sub_admin", index=True)
    # role values: super_admin, sub_admin, finance_admin, moderator, viewer
    permissions = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_login = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    def __repr__(self):
        return f"<AdminUser(id={self.id}, telegram_id={self.telegram_id}, role={self.role})>"


class PlayerNote(Base):
    __tablename__ = "player_notes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    author_id = Column(String(50), nullable=False)
    author_name = Column(String(255), nullable=True)
    note = Column(Text, nullable=False)
    is_warning = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    def __repr__(self):
        return f"<PlayerNote(id={self.id}, user_id={self.user_id})>"


class FraudFlag(Base):
    __tablename__ = "fraud_flags"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    flag_type = Column(String(50), nullable=False)
    # flag_type: rapid_deposits, multiple_accounts, unusual_play, suspicious_pattern
    severity = Column(String(20), nullable=False, default="low")
    # severity: low, medium, high
    details = Column(Text, nullable=True)
    is_resolved = Column(Boolean, nullable=False, default=False)
    resolved_by = Column(String(50), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    def __repr__(self):
        return f"<FraudFlag(id={self.id}, user_id={self.user_id}, type={self.flag_type})>"
