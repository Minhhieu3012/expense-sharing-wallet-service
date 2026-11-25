import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.exceptions import UnauthorizedException
from app.core.jwt import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    decode_token,
    get_access_token_expires_in,
)


def test_create_and_decode_access_token_uses_env_settings_and_sets_token_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 20)
    user_id = uuid.uuid4()

    # Act
    token_1 = create_access_token(user_id, extra_claims={"email": "guest@example.com"})
    token_2 = create_access_token(user_id)
    payload = decode_access_token(token_1)

    # Assert
    assert token_1 != token_2  # jti đảm bảo mỗi lần phát hành là duy nhất
    assert payload["sub"] == str(user_id)
    assert payload["token_type"] == "access"
    assert payload["email"] == "guest@example.com"
    assert payload["exp"] - payload["iat"] == 20 * 60
    assert get_access_token_expires_in() == 1200


def test_create_and_decode_refresh_token_uses_7_days_and_sets_token_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(settings, "JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7)
    user_id = uuid.uuid4()

    # Act
    token = create_refresh_token(user_id)
    payload = decode_refresh_token(token)

    # Assert
    assert payload["sub"] == str(user_id)
    assert payload["token_type"] == "refresh"
    assert payload["exp"] - payload["iat"] == 7 * 24 * 60 * 60


def test_extra_claims_cannot_override_reserved_token_type_or_sub() -> None:
    # Arrange
    real_user_id = uuid.uuid4()
    spoofed_user_id = str(uuid.uuid4())

    # Act: cố tình truyền extra_claims giả mạo token_type và sub
    token = create_access_token(
        real_user_id,
        extra_claims={"token_type": "refresh", "sub": spoofed_user_id},
    )
    payload = decode_access_token(token)

    # Assert: các claim cốt lõi vẫn giữ đúng giá trị chuẩn
    assert payload["sub"] == str(real_user_id)
    assert payload["token_type"] == "access"


def test_decode_rejects_mismatched_token_types_with_401() -> None:
    # Arrange
    user_id = uuid.uuid4()
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id)

    # Act & Assert: gửi access_token vào hàm yêu cầu refresh_token -> 401
    with pytest.raises(UnauthorizedException) as exc_refresh:
        decode_refresh_token(access_token)
    assert exc_refresh.value.status_code == 401
    assert exc_refresh.value.code == "INVALID_TOKEN_TYPE"

    # Gửi refresh_token vào hàm yêu cầu access_token -> 401
    with pytest.raises(UnauthorizedException) as exc_access:
        decode_access_token(refresh_token)
    assert exc_access.value.status_code == 401
    assert exc_access.value.code == "INVALID_TOKEN_TYPE"


def test_decode_expired_access_and_refresh_tokens_raises_401_token_expired() -> None:
    # Arrange
    user_id = uuid.uuid4()
    expired_access = create_access_token(user_id, expires_delta=timedelta(seconds=-5))
    expired_refresh = create_refresh_token(user_id, expires_delta=timedelta(seconds=-5))

    # Act & Assert
    with pytest.raises(UnauthorizedException) as exc_a:
        decode_access_token(expired_access)
    assert exc_a.value.status_code == 401
    assert exc_a.value.code == "TOKEN_EXPIRED"

    with pytest.raises(UnauthorizedException) as exc_r:
        decode_refresh_token(expired_refresh)
    assert exc_r.value.status_code == 401
    assert exc_r.value.code == "TOKEN_EXPIRED"


def test_decode_rejects_wrong_secret_malformed_and_alg_none_tokens() -> None:
    # Arrange
    now = datetime.now(timezone.utc)
    wrong_secret_token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "token_type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        key="another-completely-different-secret-key-32-chars",
        algorithm="HS256",
    )
    alg_none_token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "token_type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        key="",
        algorithm="none",
    )

    for bad_token in [wrong_secret_token, alg_none_token, "not.a.jwt", "", "   "]:
        with pytest.raises(UnauthorizedException) as exc_info:
            decode_token(bad_token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == "INVALID_TOKEN"


def test_decode_rejects_missing_or_unknown_token_type_claim() -> None:
    # Arrange
    now = datetime.now(timezone.utc)
    missing_type_token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    unknown_type_token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "token_type": "admin",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    blank_sub_token = jwt.encode(
        {
            "sub": "   ",
            "token_type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    # Thiếu token_type -> bị chặn ngay ở options={"require": ...}
    with pytest.raises(UnauthorizedException) as exc_missing:
        decode_token(missing_type_token)
    assert exc_missing.value.code == "INVALID_TOKEN"

    # token_type lạ -> INVALID_TOKEN_TYPE
    with pytest.raises(UnauthorizedException) as exc_unknown:
        decode_token(unknown_type_token)
    assert exc_unknown.value.code == "INVALID_TOKEN_TYPE"

    # sub rỗng -> INVALID_TOKEN
    with pytest.raises(UnauthorizedException) as exc_sub:
        decode_token(blank_sub_token)
    assert exc_sub.value.code == "INVALID_TOKEN"


def test_validation_guards_for_empty_subject_and_invalid_expected_type() -> None:
    with pytest.raises(ValueError, match="Subject"):
        create_access_token("   ")

    with pytest.raises(ValueError, match="expected_type"):
        decode_token("any-token", expected_type="unknown")

    # Kiểm tra TokenType enum tương thích trực tiếp với chuỗi
    assert TokenType.ACCESS == "access"
    assert TokenType.REFRESH == "refresh"
