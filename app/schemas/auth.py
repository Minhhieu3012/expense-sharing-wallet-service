from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import MoneyDecimal, UTCDatetime


class RegisterRequest(BaseModel):
    """Schema đầu vào cho API đăng ký tài khoản (POST /api/v1/auth/register)."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=150)

    @field_validator("email", mode="before")
    @classmethod
    def strip_email_whitespace(cls, value: object) -> object:
        # Cắt khoảng trắng hai đầu trước khi EmailStr kiểm tra định dạng
        # để không phụ thuộc vào hành vi mặc định của từng phiên bản email-validator.
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        normalized = str(value).strip().lower()
        if len(normalized) > 255:
            raise ValueError("Email không được vượt quá 255 ký tự.")
        return normalized

    @field_validator("password", mode="after")
    @classmethod
    def validate_password_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Mật khẩu không được chỉ chứa khoảng trắng.")
        return value

    @field_validator("full_name", mode="after")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Họ tên không được để trống.")
        return cleaned


class UserResponse(BaseModel):
    """Thông tin người dùng trả về qua API (tuyệt đối không chứa password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    created_at: UTCDatetime


class WalletSummaryResponse(BaseModel):
    """Thông tin tóm tắt ví cá nhân khi khởi tạo tài khoản."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    balance: MoneyDecimal
    currency: str


class RegisterResponse(BaseModel):
    """Schema phản hồi 201 Created cho API đăng ký tài khoản & khởi tạo ví."""

    user: UserResponse
    wallet: WalletSummaryResponse


__all__ = [
    "RegisterRequest",
    "RegisterResponse",
    "UserResponse",
    "WalletSummaryResponse",
]
