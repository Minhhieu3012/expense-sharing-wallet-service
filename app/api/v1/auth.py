from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.auth import RegisterRequest, RegisterResponse
from app.services.auth_service import register_user

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
