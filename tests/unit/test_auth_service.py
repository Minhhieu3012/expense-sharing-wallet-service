import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.jwt import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    get_access_token_expires_in,
)
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest
from app.services.auth_service import login_user, refresh_access_token, register_user


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


def test_login_user_succeeds_with_normalized_email_and_returns_valid_token_pair() -> None:
    # Arrange
    user_id = uuid.uuid4()
    stored_user = User(
        id=user_id,
        email="guest@example.com",
        password_hash=hash_password("StrongPassword@123"),
        full_name="Nguyễn Văn A",
    )
    db = MagicMock()
    db.scalar.return_value = stored_user

    payload = LoginRequest(
        email="  Guest@Example.COM  ",
        password="StrongPassword@123",
    )

    # Act
    result = login_user(db, payload)

    # Assert
    assert result.token_type == "bearer"
    assert result.expires_in == get_access_token_expires_in()

    access_claims = decode_access_token(result.access_token)
    refresh_claims = decode_refresh_token(result.refresh_token)
    assert access_claims["sub"] == str(user_id)
    assert access_claims["token_type"] == "access"
    assert refresh_claims["sub"] == str(user_id)
    assert refresh_claims["token_type"] == "refresh"


def test_login_user_raises_401_with_uniform_message_when_email_missing_or_wrong_password() -> None:
    # Arrange 1: email không tồn tại
    db_missing = MagicMock()
    db_missing.scalar.return_value = None

    with pytest.raises(UnauthorizedException) as exc_missing:
        login_user(
            db_missing,
            LoginRequest(email="nobody@example.com", password="StrongPassword@123"),
        )

    # Arrange 2: email đúng nhưng mật khẩu sai
    stored_user = User(
        id=uuid.uuid4(),
        email="guest@example.com",
        password_hash=hash_password("CorrectPassword@123"),
        full_name="Nguyễn Văn A",
    )
    db_wrong_pw = MagicMock()
    db_wrong_pw.scalar.return_value = stored_user

    with pytest.raises(UnauthorizedException) as exc_wrong_pw:
        login_user(
            db_wrong_pw,
            LoginRequest(email="guest@example.com", password="WrongPassword@999"),
        )

    # Assert: cả 2 trường hợp đều trả 401 INVALID_CREDENTIALS với cùng message (chống dò email)
    assert exc_missing.value.status_code == 401
    assert exc_missing.value.code == "INVALID_CREDENTIALS"
    assert exc_wrong_pw.value.status_code == 401
    assert exc_wrong_pw.value.code == "INVALID_CREDENTIALS"
    assert exc_missing.value.message == exc_wrong_pw.value.message


def test_refresh_access_token_succeeds_for_valid_refresh_token_and_existing_user() -> None:
    # Arrange
    user_id = uuid.uuid4()
    refresh_token = create_refresh_token(user_id)
    db = MagicMock()
    db.scalar.return_value = user_id

    # Act
    result = refresh_access_token(
        db,
        RefreshTokenRequest(refresh_token=refresh_token),
    )

    # Assert
    assert result.token_type == "bearer"
    assert result.expires_in == get_access_token_expires_in()
    claims = decode_access_token(result.access_token)
    assert claims["sub"] == str(user_id)
    assert claims["token_type"] == "access"


def test_refresh_access_token_rejects_access_token_and_expired_token_with_401() -> None:
    # Arrange
    user_id = uuid.uuid4()
    access_token = create_access_token(user_id)
    expired_refresh = create_refresh_token(
        user_id,
        expires_delta=timedelta(seconds=-10),
    )
    db = MagicMock()

    # Act & Assert 1: cố tình gửi access_token vào luồng refresh -> 401 INVALID_TOKEN_TYPE
    with pytest.raises(UnauthorizedException) as exc_type:
        refresh_access_token(db, RefreshTokenRequest(refresh_token=access_token))
    assert exc_type.value.status_code == 401
    assert exc_type.value.code == "INVALID_TOKEN_TYPE"

    # Act & Assert 2: refresh_token đã hết hạn -> 401 TOKEN_EXPIRED
    with pytest.raises(UnauthorizedException) as exc_exp:
        refresh_access_token(db, RefreshTokenRequest(refresh_token=expired_refresh))
    assert exc_exp.value.status_code == 401
    assert exc_exp.value.code == "TOKEN_EXPIRED"

    db.scalar.assert_not_called()


def test_refresh_access_token_rejects_non_uuid_sub_and_deleted_user_with_401() -> None:
    # Arrange 1: token ký hợp lệ nhưng sub không phải UUID
    bad_sub_refresh = create_refresh_token("not-a-valid-uuid")
    db = MagicMock()

    with pytest.raises(UnauthorizedException) as exc_sub:
        refresh_access_token(db, RefreshTokenRequest(refresh_token=bad_sub_refresh))
    assert exc_sub.value.status_code == 401
    assert exc_sub.value.code == "INVALID_TOKEN"
    db.scalar.assert_not_called()

    # Arrange 2: refresh_token hợp lệ nhưng user không còn tồn tại trong DB
    valid_refresh = create_refresh_token(uuid.uuid4())
    db.scalar.return_value = None

    with pytest.raises(UnauthorizedException) as exc_missing_user:
        refresh_access_token(db, RefreshTokenRequest(refresh_token=valid_refresh))
    assert exc_missing_user.value.status_code == 401
    assert exc_missing_user.value.code == "UNAUTHORIZED"
