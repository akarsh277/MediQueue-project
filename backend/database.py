from sqlalchemy import create_engine, event, types, text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
import sqlite3 as _sqlite3
import os

RAW_DB_URL = os.getenv("DATABASE_URL", "sqlite:///./mediqueue.db")
if RAW_DB_URL.startswith("postgres://"):
    DATABASE_URL = RAW_DB_URL.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = RAW_DB_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite")

# ── Patch SQLite timestamp converter ─────────────────────────
# SQLite stores datetimes as text. Legacy rows may contain '' (empty
# string) which makes the built-in pysqlite converter crash with
# "Invalid isoformat string". We register a safe converter instead.
def _safe_timestamp(val: bytes):
    """Convert bytes/str datetime value; return None on empty or bad data."""
    if not val:
        return None
    try:
        s = val.decode("utf-8") if isinstance(val, bytes) else str(val)
        s = s.strip()
        if not s:
            return None
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# Register before creating the engine so it takes effect on every connection.
if IS_SQLITE:
    _sqlite3.register_converter("TIMESTAMP", _safe_timestamp)
    _sqlite3.register_converter("DATETIME", _safe_timestamp)


# SafeDateTime: stores as String, converts to datetime in Python.
# Using String as impl bypasses SQLAlchemy's Cython str_to_datetime
# processor which crashes on legacy empty-string created_at values.
class SafeDateTime(types.TypeDecorator):
    impl = types.String if IS_SQLITE else types.DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not IS_SQLITE:
            return value
        """Python datetime → SQLite string."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def process_result_value(self, value, dialect):
        if not IS_SQLITE:
            return value
        """SQLite string → Python datetime (None on empty/bad)."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).strip())
        except (ValueError, TypeError):
            return None


if IS_SQLITE:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Safe migration function for SQLite
def apply_migrations():
    with engine.begin() as conn:
        # Create wards table explicitly if this is an older DB
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS wards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            """))
        except Exception:
            pass

        for column_query in [
            "ALTER TABLE patient_visits ADD COLUMN department TEXT",
            "ALTER TABLE patient_visits ADD COLUMN serving_time DATETIME",
            "ALTER TABLE patient_visits ADD COLUMN completion_time DATETIME",
            "ALTER TABLE patient_visits ADD COLUMN discharge_time DATETIME",
            "ALTER TABLE patient_visits ADD COLUMN condition TEXT",
            "ALTER TABLE patient_visits ADD COLUMN suggested_bed TEXT",
            "ALTER TABLE patient_visits ADD COLUMN consultation_start_time DATETIME",
            "ALTER TABLE patient_visits ADD COLUMN consultation_end_time DATETIME",
            "ALTER TABLE patient_visits ADD COLUMN bed_id INTEGER",
            "ALTER TABLE beds ADD COLUMN ward_id INTEGER",
            "ALTER TABLE beds ADD COLUMN is_occupied INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN age INTEGER DEFAULT 0",
            "ALTER TABLE doctors ADD COLUMN is_available BOOLEAN DEFAULT TRUE",
            "ALTER TABLE doctors ADD COLUMN daily_cap INTEGER DEFAULT 40"
        ]:
            try:
                conn.execute(text(column_query))
            except Exception:
                pass # Column likely already exists

apply_migrations()

