from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException
from app.core.security import hash_password
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import (
    RegisterRequest,
    RegisterResponse,
    UserResponse,
    WalletSummaryResponse,
)

INITIAL_WALLET_BALANCE = Decimal("0.00")
DEFAULT_WALLET_CURRENCY = "VND"


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


__all__ = [
    "DEFAULT_WALLET_CURRENCY",
    "INITIAL_WALLET_BALANCE",
    "register_user",
]
