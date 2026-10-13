# በ database.py ፋይል ውስጥ
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL")

# ✅ ዋናው መፍትሄ፡ pool_pre_ping=True እና pool_recycle=300 መጨመር
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # ግንኙነት መቋረጡን አስቀድሞ ያረጋግጣል
    pool_recycle=300,    # ከ5 ደቂቃ በኋላ ግንኙነቱን አድሶ ያድሳል
    pool_size=5,
    max_overflow=10
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
