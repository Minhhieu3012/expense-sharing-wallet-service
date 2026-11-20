import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,  # Tu dong kiem tra dead connect truoc khi cap request, tranh loi disconnect dot ngot khi DB restart
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    # Cho toan bo SQLAlchemy ORM models
    pass


def get_db() -> Generator[Session, None, None]:
    # Dependency cung cap DB session cho moi http request va close sau khi xong
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    # Query de xac minh PostgreSQL ready
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        logger.exception("Khong the ket noi toi PostgreSQL khi kiem tra health")
        return False
