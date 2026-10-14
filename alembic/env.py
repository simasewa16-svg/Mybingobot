"""
=====================================================================
✅ Alembic Environment Configuration (alembic/env.py) - v8.1
=====================================================================
✅ DATABASE_URL ከ Environment Variable ይመጣል (hardcoded የለም)
✅ Base.metadata ን ከ models.py ይጠቀማል
✅ Offline እና Online mode ድጋፍ
✅ UTC timezone
=====================================================================
"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool, text
from alembic import context
import os
import sys

# ✅ Project root ወደ sys.path ጨምር (models ን import ለማድረግ)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ✅ Alembic Config object
config = context.config

# ✅ Logging configuration
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ✅ DATABASE_URL ን ከ Environment Variable አምጣ
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "❌ DATABASE_URL must be set for Alembic migrations. "
        "Aborting to prevent connecting to wrong database."
    )

# ✅ Heroku/Render style URL ማስተካከል
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ✅ psycopg2 driver ን ተጠቀም (database.py ጋር ይጣጣማል)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg2://", 1
    )

# ✅ Config ውስጥ URL ን አስገባ
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# ✅ Base.metadata ን ከ models.py አምጣ (autogenerate ለማድረግ)
try:
    from database import Base
    import models  # noqa: F401 — ሁሉንም ሞዴሎች መጫን አስፈላጊ ነው
    target_metadata = Base.metadata
except ImportError as e:
    raise RuntimeError(f"❌ Failed to import models: {e}")


def run_migrations_offline() -> None:
    """Offline mode — SQL script ብቻ ማዘጋጀት (DB connection ሳያስፈልግ)"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode — DB connection ጋር migration ማስኬድ"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # ✅ Timezone UTC አዘጋጅ
        try:
            connection.execute(text("SET timezone='UTC'"))
            connection.commit()
        except Exception:
            pass

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ✅ Mode መምረጥ
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
