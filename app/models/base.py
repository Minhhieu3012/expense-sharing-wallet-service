from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Quy ước đặt tên ràng buộc chuẩn hóa cho toàn bộ schema và Alembic migration.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "idx_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "chk_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Lớp cơ sở duy nhất cho toàn bộ SQLAlchemy 2.0 ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)