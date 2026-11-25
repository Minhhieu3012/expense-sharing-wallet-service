from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.services.auth_service import login_user, refresh_access_token, register_user

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Đăng ký tài khoản mới và khởi tạo ví cá nhân",
)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    """Endpoint công khai ([Auth: Public]) tạo tài khoản người dùng kèm ví 0.00 VND."""
    return register_user(db=db, payload=payload)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Đăng nhập và cấp phát cặp JWT (Access & Refresh Token)",
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Endpoint công khai ([Auth: Public]) xác thực email/mật khẩu và cấp cặp JWT."""
    return login_user(db=db, payload=payload)


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Làm mới Access Token bằng Refresh Token hợp lệ",
)
def refresh(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
) -> RefreshTokenResponse:
    """Endpoint công khai ([Auth: Public]) cấp lại Access Token mới theo cơ chế stateless."""
    return refresh_access_token(db=db, payload=payload)
