from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import settings
from app.core.exceptions import UnauthorizedException


class TokenType(StrEnum):
    """Phân loại token bắt buộc trong payload JWT."""

    ACCESS = "access"
    REFRESH = "refresh"


_VALID_TOKEN_TYPES: frozenset[str] = frozenset({TokenType.ACCESS, TokenType.REFRESH})
_REQUIRED_CLAIMS: list[str] = ["sub", "exp", "iat", "token_type"]


def get_access_token_expires_in() -> int:
    """Trả về thời hạn sống của Access Token tính bằng giây (phục vụ trường expires_in)."""
    return settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


def _create_token(
    *,
    subject: str | uuid.UUID,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    subject_str = str(subject).strip()
    if not subject_str:
        raise ValueError("Subject (sub) của JWT không được để trống.")

    now = datetime.now(timezone.utc)
    expire_at = now + expires_delta

    payload: dict[str, Any] = {}
    if extra_claims:
        payload.update(extra_claims)

    # Ghi đè các claim chuẩn sau cùng để ngăn extra_claims làm sai lệch token_type/sub/exp.
    payload.update(
        {
            "sub": subject_str,
            "token_type": str(token_type),
            "iat": now,
            "exp": expire_at,
            "jti": str(uuid.uuid4()),
        }
    )

    return jwt.encode(
        payload=payload,
        key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(
    subject: str | uuid.UUID,
    *,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Tạo Access Token ngắn hạn (mặc định nạp từ JWT_ACCESS_TOKEN_EXPIRE_MINUTES) với token_type='access'."""
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return _create_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        expires_delta=delta,
        extra_claims=extra_claims,
    )


def create_refresh_token(
    subject: str | uuid.UUID,
    *,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Tạo Refresh Token dài hạn (mặc định nạp từ JWT_REFRESH_TOKEN_EXPIRE_DAYS) với token_type='refresh'."""
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    return _create_token(
        subject=subject,
        token_type=TokenType.REFRESH,
        expires_delta=delta,
        extra_claims=extra_claims,
    )


def decode_token(
    token: str,
    *,
    expected_type: TokenType | str | None = None,
) -> dict[str, Any]:
    """Giải mã và xác thực chữ ký, thời hạn, cấu trúc claim và loại token.

    Ném UnauthorizedException (HTTP 401) cho mọi trường hợp token sai, hết hạn hoặc sai loại.
    """
    if expected_type is not None and str(expected_type) not in _VALID_TOKEN_TYPES:
        raise ValueError(f"expected_type không hợp lệ: {expected_type!r}")

    if not isinstance(token, str) or not token.strip():
        raise UnauthorizedException(
            message="Token xác thực không hợp lệ.",
            code="INVALID_TOKEN",
        )

    try:
        payload: dict[str, Any] = jwt.decode(
            jwt=token.strip(),
            key=settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": _REQUIRED_CLAIMS},
        )
    except ExpiredSignatureError as exc:
        raise UnauthorizedException(
            message="Token xác thực đã hết hạn.",
            code="TOKEN_EXPIRED",
        ) from exc
    except InvalidTokenError as exc:
        raise UnauthorizedException(
            message="Token xác thực không hợp lệ.",
            code="INVALID_TOKEN",
        ) from exc

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise UnauthorizedException(
            message="Token xác thực không hợp lệ.",
            code="INVALID_TOKEN",
        )

    actual_type = payload.get("token_type")
    if not isinstance(actual_type, str) or actual_type not in _VALID_TOKEN_TYPES:
        raise UnauthorizedException(
            message="Loại token không hợp lệ.",
            code="INVALID_TOKEN_TYPE",
        )

    if expected_type is not None and actual_type != str(expected_type):
        raise UnauthorizedException(
            message="Loại token không phù hợp với yêu cầu.",
            code="INVALID_TOKEN_TYPE",
        )

    return payload


def decode_access_token(token: str) -> dict[str, Any]:
    """Giải mã và bắt buộc kiểm tra token có token_type == 'access'."""
    return decode_token(token, expected_type=TokenType.ACCESS)


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Giải mã và bắt buộc kiểm tra token có token_type == 'refresh'."""
    return decode_token(token, expected_type=TokenType.REFRESH)


__all__ = [
    "TokenType",
    "create_access_token",
    "create_refresh_token",
    "decode_access_token",
    "decode_refresh_token",
    "decode_token",
    "get_access_token_expires_in",
]
