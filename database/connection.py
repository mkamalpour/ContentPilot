"""Lazy database access; importing modules never creates or changes user data."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.config import DATABASE_URL

DB_URL = DATABASE_URL
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False, "timeout": 30}
    if DB_URL.startswith("sqlite")
    else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
