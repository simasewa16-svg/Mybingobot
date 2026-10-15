import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ለ PythonAnywhere ነፃ ፕላን SQLite እንጠቀማለን
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bingobot.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # ለ SQLite ግዴታ
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ሰንጠረዦችን ለመፍጠር (Alembic ስለጠቀምን ይህን አንድ ጊዜ ማሰራት)
def init_db():
    Base.metadata.create_all(bind=engine)
