"""
=====================================================================
✅ የዳታቤዝ ማዋቀሪያ (database.py) - v8.2 FINAL (Connection Stability)
=====================================================================
✅ Fail-fast: DATABASE_URL ካልተዋቀረ አፑ ፈጽሞ አይነሳም
✅ psycopg2 driver (requirements.txt ጋር ይጣጣማል)
✅ pool_pre_ping + pool_recycle=60 (የRender PG ገደብ ለማስተካከል)
✅ pool_size=3 (አነስተኛ connection pool)
✅ pool_timeout=30 (ጊዜ ገደብ)
✅ UTC timezone
=====================================================================
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import OperationalError, DBAPIError
import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# ✅ Fail-fast: Production ላይ fallback የለም
if not DATABASE_URL:
    raise RuntimeError(
        "❌ DATABASE_URL must be configured before startup. "
        "Aborting to prevent data corruption."
    )

# ✅ Heroku/Render style URL ማስተካከል
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ✅ PostgreSQL መሆኑን ማረጋገጥ
if not DATABASE_URL.startswith("postgresql://"):
    raise RuntimeError("❌ PostgreSQL URL ብቻ ይፈቀዳል!")

# ✅ psycopg2 driver ን ተጠቀም (requirements.txt ጋር ይጣጣማል)
DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# =====================================================================
# ✅ Engine Configuration — ለRender ነፃ PostgreSQL የተስተካከለ
# =====================================================================
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=3,              # ✅ አነስተኛ pool (ለነፃ ፕላን)
    max_overflow=2,           # ✅ ጥቂት ተጨማሪ connections
    pool_pre_ping=True,       # ✅ ግንኙነት መቋረጡን አስቀድሞ ያረጋግጣል
    pool_recycle=60,          # ✅ ከ1 ደቂቃ በኋላ ያድሳል (ከRender 90s ገደብ በፊት)
    pool_timeout=30,          # ✅ Connection ለማግኘት ከፍተኛ ጊዜ
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


@event.listens_for(engine, "connect")
def set_timezone(dbapi_conn, conn_record):
    """የግንኙነት ጊዜ ወደ UTC አዘጋጅ"""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("SET timezone='UTC'")
    finally:
        cursor.close()


def get_db():
    """የዳታቤዝ ግንኙነት አገልግሎት — ስህተት ካለ በራሱ ይዘጋል"""
    db = SessionLocal()
    try:
        yield db
    except (OperationalError, DBAPIError) as e:
        logger.error(f"DB error in get_db: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass
