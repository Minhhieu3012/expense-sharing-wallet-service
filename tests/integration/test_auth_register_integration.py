import os
import subprocess
import sys
import uuid
from collections.abc import Generator
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_password
from app.main import app
from app.models import User, Wallet

TEST_EMAIL_DOMAIN = "@register-test.example.com"


def _cleanup_test_users(engine: Engine) -> None:
    """Dọn dẹp toàn bộ bản ghi users và wallets tạo ra bởi bộ test này (tôn trọng ON DELETE RESTRICT)."""
    with Session(engine) as session:
        user_ids = session.scalars(
            select(User.id).where(User.email.like(f"%{TEST_EMAIL_DOMAIN}"))
        ).all()
        if user_ids:
            session.execute(delete(Wallet).where(Wallet.user_id.in_(user_ids)))
            session.execute(delete(User).where(User.id.in_(user_ids)))
            session.commit()


@pytest.fixture(scope="module")
def migrated_test_engine() -> Generator[Engine, None, None]:
    """Đảm bảo expense_test_db đã chạy đủ Alembic migrations trước khi chạy Integration Tests."""
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = settings.TEST_DATABASE_URL

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
    )

    engine = create_engine(settings.TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def test_db_override(migrated_test_engine: Engine) -> Generator[Engine, None, None]:
    """Ghi đè dependency get_db để mọi HTTP request đều thao tác trên expense_test_db."""
    _cleanup_test_users(migrated_test_engine)

    test_session_local = sessionmaker(
        bind=migrated_test_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield migrated_test_engine
    finally:
        app.dependency_overrides.clear()
        _cleanup_test_users(migrated_test_engine)


# ============================================================================
# NHÓM 1: ĐĂNG KÝ THÀNH CÔNG (201 Created)
# ============================================================================


def test_register_success_creates_user_and_zero_balance_wallet_in_postgres(
    test_db_override: Engine,
) -> None:
    # Arrange
    client = TestClient(app)
    raw_password = "StrongPassword@123"
    email = f"Alice.Success{TEST_EMAIL_DOMAIN}"
    expected_email = email.lower()

    # Act
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": raw_password,
            "full_name": "Nguyễn Thị Alice",
        },
    )

    # Assert HTTP Response (201 Created + khớp hợp đồng API, không lộ password_hash)
    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"user", "wallet"}

    user_data = body["user"]
    assert set(user_data.keys()) == {"id", "email", "full_name", "created_at"}
    assert user_data["email"] == expected_email
    assert user_data["full_name"] == "Nguyễn Thị Alice"
    assert user_data["created_at"].endswith("Z")
    assert "password_hash" not in user_data
    assert "password" not in user_data
    assert raw_password not in response.text

    wallet_data = body["wallet"]
    assert set(wallet_data.keys()) == {"id", "balance", "currency"}
    assert wallet_data["balance"] == "0.00"
    assert isinstance(wallet_data["balance"], str)
    assert wallet_data["currency"] == "VND"

    # Assert trực tiếp trên PostgreSQL (expense_test_db)
    with Session(test_db_override) as verify_session:
        db_user = verify_session.scalar(
            select(User).where(User.email == expected_email)
        )
        assert db_user is not None
        assert db_user.id == uuid.UUID(user_data["id"])
        assert db_user.password_hash != raw_password
        assert db_user.password_hash.startswith("$argon2id$")
        assert verify_password(raw_password, db_user.password_hash) is True

        db_wallet = verify_session.scalar(
            select(Wallet).where(Wallet.user_id == db_user.id)
        )
        assert db_wallet is not None
        assert db_wallet.id == uuid.UUID(wallet_data["id"])
        assert isinstance(db_wallet.balance, Decimal)
        assert db_wallet.balance == Decimal("0.00")
        assert db_wallet.currency == "VND"


# ============================================================================
# NHÓM 2: KỊCH BẢN LỖI (409 Conflict & 422 Unprocessable Entity)
# ============================================================================


def test_register_duplicate_email_returns_409_conflict(
    test_db_override: Engine,
) -> None:
    # Arrange: tạo trước 1 tài khoản hợp lệ trong PostgreSQL
    client = TestClient(app)
    email = f"duplicate{TEST_EMAIL_DOMAIN}"

    first_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "StrongPassword@123",
            "full_name": "Người Dùng Đầu Tiên",
        },
    )
    assert first_response.status_code == 201

    # Act: đăng ký lại cùng email (khác chữ hoa/thường) để kiểm tra chuẩn hóa & chặn trùng
    second_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email.upper(),
            "password": "AnotherPassword@456",
            "full_name": "Người Dùng Trùng Email",
        },
    )

    # Assert: trả về 409 Conflict đúng chuẩn JSON lỗi và không tạo thêm bản ghi nào
    assert second_response.status_code == 409
    assert second_response.json() == {
        "error": {
            "code": "EMAIL_ALREADY_EXISTS",
            "message": "Email đã được sử dụng trong hệ thống.",
            "details": {"email": email},
        }
    }

    with Session(test_db_override) as verify_session:
        users = verify_session.scalars(select(User).where(User.email == email)).all()
        assert len(users) == 1
        wallets = verify_session.scalars(
            select(Wallet).where(Wallet.user_id == users[0].id)
        ).all()
        assert len(wallets) == 1


def test_register_invalid_email_returns_422_standard_error_envelope(
    test_db_override: Engine,
) -> None:
    # Arrange
    client = TestClient(app)
    secret_password = "StrongPassword@123"

    # Act
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "khong-dung-dinh-dang-email",
            "password": secret_password,
            "full_name": "Nguyễn Văn B",
        },
    )

    # Assert
    assert response.status_code == 422
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["error"]["details"], list)
    assert any(item["field"] == "body.email" for item in body["error"]["details"])
    assert secret_password not in response.text


def test_register_missing_required_fields_returns_422_standard_error_envelope(
    test_db_override: Engine,
) -> None:
    # Arrange
    client = TestClient(app)

    # Act: gửi payload rỗng thiếu toàn bộ các trường bắt buộc
    response = client.post("/api/v1/auth/register", json={})

    # Assert
    assert response.status_code == 422
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "VALIDATION_ERROR"
    missing_fields = {item["field"] for item in body["error"]["details"]}
    assert missing_fields == {"body.email", "body.password", "body.full_name"}


# ============================================================================
# NHÓM 3: KIỂM CHỨNG GIAO DỊCH ACID / ROLLBACK TRÊN POSTGRESQL THỰC TẾ
# ============================================================================


def test_register_rolls_back_user_when_wallet_instantiation_raises_error(
    test_db_override: Engine,
) -> None:
    # Arrange: sau khi User đã được db.flush() xuống PostgreSQL, giả lập lỗi lúc khởi tạo Wallet
    client = TestClient(app, raise_server_exceptions=False)
    email = f"rollback.app.error{TEST_EMAIL_DOMAIN}"

    with patch(
        "app.services.auth_service.Wallet",
        side_effect=RuntimeError("Simulated wallet creation crash"),
    ):
        # Act
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPassword@123",
                "full_name": "Rollback App Error User",
            },
        )

    # Assert: trả về 500 chuẩn (không lộ stack trace) và bản ghi users đã được rollback sạch
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.",
            "details": None,
        }
    }
    assert "Simulated wallet creation crash" not in response.text

    with Session(test_db_override) as verify_session:
        orphan_user = verify_session.scalar(select(User).where(User.email == email))
        assert orphan_user is None


def test_register_rolls_back_user_when_wallet_db_constraint_fails(
    test_db_override: Engine,
) -> None:
    # Arrange: giả lập số dư khởi tạo âm (-1.00) để PostgreSQL từ chối INSERT wallets
    # (vi phạm chk_wallets_balance_non_negative) SAU KHI users đã được flush trong transaction.
    client = TestClient(app, raise_server_exceptions=False)
    email = f"rollback.db.constraint{TEST_EMAIL_DOMAIN}"

    with patch("app.services.auth_service.INITIAL_WALLET_BALANCE", Decimal("-1.00")):
        # Act
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "StrongPassword@123",
                "full_name": "Rollback DB Constraint User",
            },
        )

    # Assert: trả về 500 chuẩn và PostgreSQL đã rollback hoàn toàn cả bản ghi users
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"

    with Session(test_db_override) as verify_session:
        orphan_user = verify_session.scalar(select(User).where(User.email == email))
        assert orphan_user is None
