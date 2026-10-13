"""
=====================================================================
✅ Alembic Environment Configuration (alembic/env.py)
=====================================================================
- DATABASE_URL ከ environment ያነባል
- ሁሉንም models ሜታዳታ ያገናኛል
- PostgreSQL-only ማረጋገጫ
=====================================================================
"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool, text
from alembic import context
import os
import sys

# ✅ የፕሮጀክቱን root ወደ sys.path ጨምር
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ✅ የ models ሜታዳታ አምጣ
from database import Base
import models  # noqa: F401 - ሁሉንም ሠንጠረዦች ለማስመዝገብ ያስፈልጋል

# ✅ Alembic Config object
config = context.config

# ✅ Logging ማዋቀር
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ✅ ሁሉንም ሠንጠረዦች ለማወቅ
target_metadata = Base.metadata


def get_database_url():
    """✅ DATABASE_URL ከ environment ማምጣት"""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "❌ DATABASE_URL environment variable is not set!"
        )
    # ✅ Heroku/Render style URL ማስተካከል
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if not url.startswith("postgresql://"):
        raise RuntimeError(
            "❌ Only PostgreSQL URLs are supported!"
        )
    return url


def run_migrations_offline() -> None:
    """✅ Offline mode - SQL script ብቻ ያመነጫል"""
    url = get_database_url()
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
    """✅ Online mode - ከዳታቤዝ ጋር ተገናኝቶ migration ያስኬዳል"""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # ✅ PostgreSQL ማረጋገጥ
        connection.execute(text("SELECT version()"))

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=False,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
