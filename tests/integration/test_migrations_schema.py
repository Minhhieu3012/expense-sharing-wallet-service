import os
import subprocess
import sys
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Category, User, Wallet

EXPECTED_TABLES = {
    "users",
    "wallets",
    "groups",
    "group_members",
    "categories",
    "expenses",
    "expense_splits",
    "settlements",
    "ledger_transactions",
}

EXPECTED_INDEXES = {
    "idx_group_members_user_id",
    "idx_expenses_group_date",
    "idx_expenses_paid_by_date",
    "idx_expense_splits_expense_id",
    "idx_expense_splits_user_id",
    "idx_settlements_group_id",
    "idx_ledger_wallet_created",
}

EXPECTED_CATEGORY_CODES = {
    "FOOD",
    "TRANSPORT",
    "ACCOMMODATION",
    "UTILITIES",
    "ENTERTAINMENT",
}


@pytest.fixture(scope="module")
def migrated_test_engine():
    """Chạy alembic upgrade head trên expense_test_db trước khi kiểm chứng schema."""
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = settings.TEST_DATABASE_URL

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
    )

    engine = create_engine(settings.TEST_DATABASE_URL)
    yield engine
    engine.dispose()


def test_all_nine_tables_and_seven_custom_indexes_exist(migrated_test_engine) -> None:
    # Arrange
    inspector = inspect(migrated_test_engine)

    # Act
    existing_tables = set(inspector.get_table_names())
    existing_indexes: set[str] = set()
    for table_name in EXPECTED_TABLES:
        for idx in inspector.get_indexes(table_name):
            if idx["name"]:
                existing_indexes.add(idx["name"])

    # Assert
    assert EXPECTED_TABLES.issubset(existing_tables)
    assert EXPECTED_INDEXES.issubset(existing_indexes)


def test_default_categories_are_seeded(migrated_test_engine) -> None:
    # Arrange & Act
    with Session(migrated_test_engine) as session:
        codes = set(session.scalars(select(Category.code)).all())

    # Assert
    assert EXPECTED_CATEGORY_CODES.issubset(codes)


def test_wallet_balance_check_constraint_rejects_negative_value(migrated_test_engine) -> None:
    # Arrange
    with Session(migrated_test_engine) as session:
        user = User(
            email="negative_balance_check@example.com",
            password_hash="hashed_password",
            full_name="Test Constraint User",
        )
        session.add(user)
        session.flush()

        invalid_wallet = Wallet(user_id=user.id, balance=Decimal("-1.00"))
        session.add(invalid_wallet)

        # Act & Assert
        with pytest.raises(IntegrityError):
            session.flush()

        # Dọn dẹp transaction để không để lại dữ liệu rác trong expense_test_db
        session.rollback()