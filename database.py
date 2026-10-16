import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# የ Neon ዳታቤዝ ሊንክህን እዚህ አስገባ
DATABASE_URL = "postgresql://neondb_owner:ይለፍ_ቃል@ep-blue-hill-b435p09a-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
