"""
=====================================================================
✅ የዳታቤዝ ማዋቀሪያ (database.py)
=====================================================================
- PostgreSQL-only
- psycopg3 (v3) driver
- Connection pooling ለProduction
- UTC timezone
=====================================================================
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = "postgresql+psycopg://user:password@localhost/bingo"
    logger.warning("⚠️ DATABASE_URL not set, using fallback!")

# ✅ Heroku/Render style URL ማስተካከል
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ✅ PostgreSQL መሆኑን ማረጋገጥ
if not DATABASE_URL.startswith("postgresql://"):
    raise RuntimeError("❌ PostgreSQL URL ብቻ ይፈቀዳል!")

# ✅ psycopg3 (v3) driver ን ተጠቀም - Python 3.14 ይደግፋል!
DATABASE_URL = DATABASE_URL.replace(
    "postgresql://", "postgresql+psycopg://", 1
)

# ==================== Engine መፍጠር ====================
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=False,
    future=True,
)

# ==================== Session Factory ====================
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
    future=True,
)

Base = declarative_base()


@event.listens_for(engine, "connect")
def set_timezone(dbapi_conn, conn_record):
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("SET timezone='UTC'")
    finally:
        cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
