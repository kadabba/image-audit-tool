import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .models import Base

# Папка для БД
DB_DIR = os.path.join(os.path.dirname(__file__), "../../data")
os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "audit.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Создаём engine с check_same_thread=False для многопоточности
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


# Включаем WAL-режим для параллельных read/write
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


# Создаём таблицы
Base.metadata.create_all(bind=engine)

# Sessionmaker для dependency injection в FastAPI
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency для получения сессии БД в роутах."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
