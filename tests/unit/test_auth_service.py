import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictException
from app.core.security import verify_password
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import RegisterRequest
from app.services.auth_service import register_user


def _build_mock_db(existing_user_id: uuid.UUID | None = None) -> MagicMock:
    db = MagicMock()
    db.scalar.return_value = existing_user_id
    added_objects: list[object] = []
    db._added_objects = added_objects

    def fake_add(obj: object) -> None:
        added_objects.append(obj)

    def fake_refresh(obj: object) -> None:
        now = datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc)
        if isinstance(obj, User):
            if obj.id is None:
                obj.id = uuid.uuid4()
            if obj.created_at is None:
                obj.created_at = now
        elif isinstance(obj, Wallet):
            if obj.id is None:
                obj.id = uuid.uuid4()

    db.add.side_effect = fake_add
    db.refresh.side_effect = fake_refresh
    return db


def test_register_user_creates_user_and_wallet_in_single_transaction() -> None:
    # Arrange
    db = _build_mock_db(existing_user_id=None)
    payload = RegisterRequest(
        email="Guest@Example.com",
        password="StrongPassword@123",
        full_name="Nguyễn Văn A",
    )

    # Act
    result = register_user(db, payload)

    # Assert: kiểm tra 2 ORM objects được thêm trong cùng 1 transaction
    assert len(db._added_objects) == 2
    created_user, created_wallet = db._added_objects
    assert isinstance(created_user, User)
    assert isinstance(created_wallet, Wallet)

    # Kiểm tra mật khẩu đã được băm Argon2id, tuyệt đối không lưu plaintext
    assert created_user.password_hash != "StrongPassword@123"
    assert created_user.password_hash.startswith("$argon2id$")
    assert verify_password("StrongPassword@123", created_user.password_hash) is True

    # Kiểm tra ví khởi tạo đúng Decimal("0.00") và currency="VND", tuyệt đối không dùng float
    assert created_wallet.user_id == created_user.id
    assert isinstance(created_wallet.balance, Decimal)
    assert not isinstance(created_wallet.balance, float)
    assert created_wallet.balance == Decimal("0.00")
    assert created_wallet.currency == "VND"

    # Kiểm tra transaction commit đúng 1 lần và không rollback
    db.flush.assert_called_once()
    db.commit.assert_called_once()
    db.rollback.assert_not_called()

    # Kiểm tra dữ liệu trả về khớp API contract
    dumped = result.model_dump(mode="json")
    assert dumped["user"]["email"] == "guest@example.com"
    assert dumped["user"]["full_name"] == "Nguyễn Văn A"
    assert dumped["user"]["created_at"] == "2026-11-24T10:00:00Z"
    assert "password_hash" not in dumped["user"]
    assert dumped["wallet"]["balance"] == "0.00"
    assert dumped["wallet"]["currency"] == "VND"


def test_register_user_raises_409_when_email_already_exists() -> None:
    # Arrange
    db = _build_mock_db(existing_user_id=uuid.uuid4())
    payload = RegisterRequest(
        email="existing@example.com",
        password="StrongPassword@123",
        full_name="Existing User",
    )

    # Act & Assert
    with pytest.raises(ConflictException) as exc_info:
        register_user(db, payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "EMAIL_ALREADY_EXISTS"
    assert exc_info.value.details == {"email": "existing@example.com"}
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_register_user_rolls_back_and_raises_409_on_concurrent_unique_email_violation() -> None:
    # Arrange: giả lập race condition khi 2 request cùng vượt qua SELECT rồi đụng uq_users_email
    db = _build_mock_db(existing_user_id=None)
    orig_err = Exception('duplicate key value violates unique constraint "uq_users_email"')
    db.flush.side_effect = IntegrityError("INSERT INTO users ...", {}, orig_err)

    payload = RegisterRequest(
        email="race@example.com",
        password="StrongPassword@123",
        full_name="Race Condition User",
    )

    # Act & Assert
    with pytest.raises(ConflictException) as exc_info:
        register_user(db, payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "EMAIL_ALREADY_EXISTS"
    assert exc_info.value.details == {"email": "race@example.com"}
    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_register_user_rolls_back_transaction_when_wallet_creation_or_commit_fails() -> None:
    # Arrange: giả lập lỗi giữa transaction khi commit tạo user + wallet
    db = _build_mock_db(existing_user_id=None)
    db.commit.side_effect = RuntimeError("Simulated DB failure before commit")

    payload = RegisterRequest(
        email="rollback@example.com",
        password="StrongPassword@123",
        full_name="Rollback User",
    )

    # Act & Assert
    with pytest.raises(RuntimeError, match="Simulated DB failure"):
        register_user(db, payload)

    db.rollback.assert_called_once()


def test_register_user_re_raises_non_email_integrity_error_after_rollback() -> None:
    # Arrange: lỗi IntegrityError khác (không phải trùng email) không được biến thành 409 email
    db = _build_mock_db(existing_user_id=None)
    orig_err = Exception('new row violates check constraint "chk_wallets_balance_non_negative"')
    db.commit.side_effect = IntegrityError("INSERT INTO wallets ...", {}, orig_err)

    payload = RegisterRequest(
        email="other-integrity@example.com",
        password="StrongPassword@123",
        full_name="Other Integrity User",
    )

    # Act & Assert
    with pytest.raises(IntegrityError):
        register_user(db, payload)

    db.rollback.assert_called_once()
