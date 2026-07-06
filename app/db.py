from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import get_settings
from app.models import Base

engine = create_engine(
    get_settings().database_url, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _add_missing_columns() -> None:
    with engine.connect() as conn:
        existing = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(learned_selectors)")
        }
        if existing and "empty_streak" not in existing:
            conn.exec_driver_sql(
                "ALTER TABLE learned_selectors ADD COLUMN empty_streak INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()
