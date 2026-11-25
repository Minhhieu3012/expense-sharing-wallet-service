from __future__ import annotations

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import UnauthorizedException
from app.core.jwt import decode_access_token
from app.models.user import User

# Dùng auto_error=False để tránh hành vi mặc định của FastAPI HTTPBearer trả về 403
# khi thiếu header Authorization; thay vào đó luôn chuẩn hóa về 401 Unauthorized.
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Nhập Access Token theo định dạng Bearer <access_token>.",
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency xác thực JWT Bearer cho các endpoint bảo vệ ([Auth: Bearer]).

    Kiểm tra header Authorization: Bearer, chữ ký, hạn dùng, token_type == 'access',
    và sự tồn tại của người dùng trong cơ sở dữ liệu.
    """
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials.strip()
    ):
        raise UnauthorizedException(
            message="Thiếu hoặc sai định dạng header Authorization: Bearer.",
            code="UNAUTHORIZED",
        )

    claims = decode_access_token(credentials.credentials)

    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (ValueError, TypeError) as exc:
        raise UnauthorizedException(
            message="Token xác thực không hợp lệ.",
            code="INVALID_TOKEN",
        ) from exc

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise UnauthorizedException(
            message="Tài khoản gắn với token không tồn tại.",
            code="UNAUTHORIZED",
        )

    return user


__all__ = [
    "bearer_scheme",
    "get_current_user",
]
