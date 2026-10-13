"""
=====================================================================
✅ የዳታቤዝ ማዋቀሪያ (database.py)
=====================================================================
- PostgreSQL-only (SQLite አይደግፍም)
- Connection pooling ለProduction
- UTC timezone
- pool_pre_ping (የሞተ connection ያድሳል)
=====================================================================
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
import os
import logging

logger = logging.getLogger(__name__)

# ✅ DATABASE_URL ከ environment variable
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # ለአካባቢ ልማት ብቻ fallback
    DATABASE_URL = "postgresql://user:password@localhost/bingo"
    logger.warning("⚠️ DATABASE_URL not set, using fallback!")

# ✅ Heroku/Render style URL ማስተካከል
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ✅ PostgreSQL መሆኑን ማረጋገጥ
if not DATABASE_URL.startswith("postgresql://"):
    raise RuntimeError("❌ PostgreSQL URL ብቻ ይፈቀዳል!")

# ✅ Connection pooling (Production-ready)
# ✅ SQLAlchemy ትክክለኛውን driver እንዲመርጥ
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,      # የሞተ connection ያድሳል
    pool_recycle=300,        # በየ 5 ደቂቃው ያድሳል
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
    future=True,
)

Base = declarative_base()

# ✅ PostgreSQL ላይ UTC ማረጋገጥ
@event.listens_for(engine, "connect")
def set_timezone(dbapi_conn, conn_record):
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("SET timezone='UTC'")
    finally:
        cursor.close()


def get_db():
    """FastAPI dependency - ሁልጊዜ session ይዘጋል"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
