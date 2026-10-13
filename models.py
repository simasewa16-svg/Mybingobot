"""
=====================================================================
✅ የዳታቤዝ ሞዴሎች (models.py)
=====================================================================
ዋና የደህንነት መርሆች፦
1. ሁሉም የገንዘብ መጠኖች Numeric(12,2) - Float አይደለም!
2. ሁሉም የገንዘብ እንቅስቃሴ Ledger ይመዘገባል
3. UniqueConstraint ድግግሞሽ (idempotency) ይከላከላል
4. Partial Index አንድ ንቁ ጨዋታ ብቻ ያረጋግጣል
=====================================================================
"""
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, ForeignKey,
    DateTime, Text, UniqueConstraint, Index, CheckConstraint, text
)
from datetime import datetime
from database import Base


class User(Base):
    """✅ የተጠቃሚ መዝገብ - ባላንስ እና ማንነት"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, nullable=True)
    # ✅ የገንዘብ ትክክለኛነት - Numeric ብቻ!
    balance = Column(Numeric(12, 2), default=0.00, nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # ✅ ባላንስ አሉታዊ አይሁን!
    __table_args__ = (
        CheckConstraint('balance >= 0', name='ck_user_balance_non_negative'),
    )


class Game(Base):
    """
    ✅ የBingo ጨዋታ ሁኔታ
    ሁኔታዎች፦ waiting → playing → finished/cancelled
    """
    __tablename__ = "games"
    
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, default="waiting", nullable=False)
    jackpot = Column(Numeric(12, 2), default=0.00, nullable=False)
    card_price = Column(Numeric(12, 2), default=10.00, nullable=False)
    call_count = Column(Integer, default=0, nullable=False)
    
    # ✅ የተጠሩ ቁጥሮች በተጠሩበት ቅደም ተከተል
    called_numbers = Column(Text, default="", nullable=False)
    last_number = Column(Integer, nullable=True)
    last_drawn_at = Column(DateTime, nullable=True)
    
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # ✅ ድግግሞሽ መከላከያዎች
    refunded = Column(Boolean, default=False, nullable=False)
    payout_completed = Column(Boolean, default=False, nullable=False)
    
    # ✅ ካለ አሸናፊ ወደ ቀጣይ ጨዋታ የሚተላለፍ
    rollover_jackpot = Column(Numeric(12, 2), default=0.00, nullable=False)
    
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # ✅ አንድ ጊዜ ብቻ ንቁ ጨዋታ (Partial Unique Index)
    #    ይህ በconcurrent ሁኔታ ብዙ ጨዋታዎች እንዳይፈጠሩ ይከላከላል
    __table_args__ = (
        Index(
            'uq_single_active_game',
            text("(status IN ('waiting','playing'))"),
            unique=True,
            postgresql_where=text("status IN ('waiting','playing')"),
        ),
    )


class Card(Base):
    """✅ የተጫዋች የBingo ካርድ"""
    __tablename__ = "cards"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    numbers = Column(Text, nullable=False)  # "1,16,31,..." (25 ቁጥሮች)
    is_winner = Column(Boolean, default=False, nullable=False)
    
    # ✅ የካርድ ዋጋ ተቆልፎ ይያዝ (Refund በትክክል እንዲመለስ)
    price_paid = Column(Numeric(12, 2), default=10.00, nullable=False)
    
    # ✅ የRefund ድግግሞሽ መከላከያ
    refunded = Column(Boolean, default=False, nullable=False)
    refunded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # ✅ አንድ ተጠቃሚ በአንድ ጨዋታ አንድ ካርድ ብቻ
    __table_args__ = (
        UniqueConstraint('user_id', 'game_id', name='uq_user_game_card'),
    )


class Transaction(Base):
    """✅ የክፍያ ጥያቄ (Telebirr/CBE Birr)"""
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)
    method = Column(String, nullable=False)
    status = Column(String, default="pending", nullable=False)
    
    # ✅ የደረሰኝ ቁጥር ልዩ መሆን አለበት (replay attack መከላከያ)
    reference = Column(String, unique=True, nullable=False, index=True)
    
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        CheckConstraint('amount > 0', name='ck_transaction_amount_positive'),
    )


class AuditLog(Base):
    """
    ✅ የAdmin ድርጊቶች ማህደር
    የማይለወጥ (Immutable) - ለህጋዊ እና ለሂሳብ ኦዲት
    """
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class LedgerEntry(Base):
    """
    =========================================================
    ✅ የገንዘብ መዝገብ (Double-Entry Protection)
    =========================================================
    ዓይነቶች (entry_type)፦
      - deposit_approved : ገንዘብ ገቢ
      - card_purchase    : ካርድ ግዢ (አሉታዊ)
      - prize_payout     : ሽልማት ክፍያ
      - refund           : ጨዋታ ሰርዞ ገንዘብ መመለስ
      - jackpot_rollover : ካለ አሸናፊ ወደ ቀጣይ ማስተላለፍ
    
    ✅ UniqueConstraint ሁለት ተመሳሳይ ክፍያዎችን 
       ለአንድ ተጠቃሚ አንድ ጊዜ ብቻ እንዲፈጸሙ ያረጋግጣል።
    =========================================================
    """
    __tablename__ = "ledger_entries"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String, nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False)  # አዎንታዊ = ገቢ, አሉታዊ = ወጪ
    balance_after = Column(Numeric(12, 2), nullable=False)
    reference_type = Column(String, nullable=True)  # card, game, transaction
    reference_id = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # ✅ ድግግሞሽ መከላከያ - አንድ ዓይነት እንቅስቃሴ ለአንድ ተጠቃሚ 
    #    ለአንድ ማጣቀሻ አንድ ጊዜ ብቻ!
    __table_args__ = (
        UniqueConstraint(
            'user_id', 'entry_type', 'reference_type', 'reference_id',
            name='uq_ledger_no_duplicate'
        ),
    )
