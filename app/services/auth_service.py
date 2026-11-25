from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.jwt import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_access_token_expires_in,
)
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
    WalletSummaryResponse,
)

INITIAL_WALLET_BALANCE = Decimal("0.00")
DEFAULT_WALLET_CURRENCY = "VND"

# Sinh sẵn 1 chuỗi hash giả lập lúc nạp module để cân bằng thời gian băm Argon2id
# khi đăng nhập bằng email không tồn tại (chống dò email qua timing side-channel).
_DUMMY_PASSWORD_HASH = hash_password("dummy-timing-mitigation-secret")
_INVALID_CREDENTIALS_MESSAGE = "Email hoặc mật khẩu không chính xác."


def _is_duplicate_email_error(exc: IntegrityError) -> bool:
    """Xác định IntegrityError có xuất phát từ ràng buộc duy nhất uq_users_email hay không."""
    orig = exc.orig
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name == "uq_users_email":
        return True

    pgcode = getattr(orig, "pgcode", None)
    message = str(orig) if orig is not None else str(exc)
    if pgcode == "23505" and "email" in message.lower():
        return True
    return "uq_users_email" in message


def register_user(db: Session, payload: RegisterRequest) -> RegisterResponse:
    """Đăng ký tài khoản mới và khởi tạo ví cá nhân (0.00 VND) trong một Transaction duy nhất."""
    normalized_email = str(payload.email).strip().lower()

    # Kiểm tra trùng email trước khi băm mật khẩu để tránh tốn CPU/RAM Argon2id không cần thiết.
    existing_user_id = db.scalar(select(User.id).where(User.email == normalized_email))
    if existing_user_id is not None:
        raise ConflictException(
            message="Email đã được sử dụng trong hệ thống.",
            code="EMAIL_ALREADY_EXISTS",
            details={"email": normalized_email},
        )

    password_hash = hash_password(payload.password)

    try:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=normalized_email,
            password_hash=password_hash,
            full_name=payload.full_name,
        )
        db.add(user)
        # Flush để áp dụng bản ghi users (và kiểm tra uq_users_email) trước khi chèn wallets.
        db.flush()

        wallet = Wallet(
            user_id=user.id,
            balance=INITIAL_WALLET_BALANCE,
            currency=DEFAULT_WALLET_CURRENCY,
        )
        db.add(wallet)
        db.commit()

        db.refresh(user)
        db.refresh(wallet)
    except IntegrityError as exc:
        db.rollback()
        if _is_duplicate_email_error(exc):
            raise ConflictException(
                message="Email đã được sử dụng trong hệ thống.",
                code="EMAIL_ALREADY_EXISTS",
                details={"email": normalized_email},
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    return RegisterResponse(
        user=UserResponse.model_validate(user),
        wallet=WalletSummaryResponse.model_validate(wallet),
    )


def login_user(db: Session, payload: LoginRequest) -> LoginResponse:
    """Xác thực email/mật khẩu và cấp phát cặp Access Token + Refresh Token."""
    normalized_email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))

    if user is None:
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)
        raise UnauthorizedException(
            message=_INVALID_CREDENTIALS_MESSAGE,
            code="INVALID_CREDENTIALS",
        )

    if not verify_password(payload.password, user.password_hash):
        raise UnauthorizedException(
            message=_INVALID_CREDENTIALS_MESSAGE,
            code="INVALID_CREDENTIALS",
        )

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=get_access_token_expires_in(),
    )


def refresh_access_token(
    db: Session,
    payload: RefreshTokenRequest,
) -> RefreshTokenResponse:
    """Kiểm tra Refresh Token hợp lệ (token_type='refresh', user còn tồn tại) và cấp mới Access Token."""
    claims = decode_refresh_token(payload.refresh_token)

    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (ValueError, TypeError) as exc:
        raise UnauthorizedException(
            message="Token xác thực không hợp lệ.",
            code="INVALID_TOKEN",
        ) from exc

    existing_user_id = db.scalar(select(User.id).where(User.id == user_id))
    if existing_user_id is None:
        raise UnauthorizedException(
            message="Tài khoản gắn với token không tồn tại.",
            code="UNAUTHORIZED",
        )

    new_access_token = create_access_token(existing_user_id)
    return RefreshTokenResponse(
        access_token=new_access_token,
        expires_in=get_access_token_expires_in(),
    )


__all__ = [
    "DEFAULT_WALLET_CURRENCY",
    "INITIAL_WALLET_BALANCE",
    "login_user",
    "refresh_access_token",
    "register_user",
]
