from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, DATABASE_URL

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from sqlalchemy import text

    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # Leichte SQLite-Migrationen für bestehende DBs
    with engine.begin() as conn:
        sample_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(samples)")).fetchall()
        }
        if "avg_intensity_mps" not in sample_cols:
            conn.execute(text("ALTER TABLE samples ADD COLUMN avg_intensity_mps FLOAT"))
        user_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        if "sex" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN sex VARCHAR(8)"))
        if "birth_year" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN birth_year INTEGER"))
