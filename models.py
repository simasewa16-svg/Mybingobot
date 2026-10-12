from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String, unique=True, index=True)
    username = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, default="waiting") # waiting, playing, finished
    jackpot = Column(Float, default=0.0)
    call_count = Column(Integer, default=0)
    called_numbers = Column(String, default="") # "1,5,20,..." ብለን እናስቀምጣለን

class Card(Base):
    __tablename__ = "cards"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    game_id = Column(Integer, ForeignKey("games.id"))
    numbers = Column(String) # "1,16,31,46,61,..."

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Float)
    method = Column(String) # Telebirr or CBE
    status = Column(String, default="pending") # pending, approved, rejected
    reference = Column(String, unique=True) # የደረሰኝ ቁጥር
    created_at = Column(DateTime, default=datetime.utcnow)
