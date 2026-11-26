from __future__ import annotations

import re
import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.common import (
    UTCDatetime,
    normalize_email,
    strip_email_whitespace,
)

_CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")


class GroupRole(StrEnum):
    """Vai trò thành viên trong nhóm chi tiêu (khớp ràng buộc chk_group_members_role)."""

    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class GroupCreateRequest(BaseModel):
    """Schema đầu vào cho API tạo nhóm chi tiêu mới (POST /api/v1/groups)."""

    name: str = Field(..., min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    currency: str = Field(default="VND", min_length=3, max_length=3)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("currency", mode="after")
    @classmethod
    def validate_currency_format(cls, value: str) -> str:
        if not _CURRENCY_CODE_PATTERN.match(value):
            raise ValueError(
                "Đơn vị tiền tệ phải gồm đúng 3 chữ cái in hoa theo chuẩn ISO 4217 (ví dụ: VND, USD)."
            )
        return value


class GroupResponse(BaseModel):
    """Schema phản hồi thông tin nhóm mới tạo kèm vai trò của người dùng (ADMIN khi khởi tạo)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    currency: str
    created_by: uuid.UUID
    role: GroupRole
    created_at: UTCDatetime


class GroupMemberAddRequest(BaseModel):
    """Schema đầu vào cho API thêm thành viên vào nhóm bằng email (POST /api/v1/groups/{group_id}/members)."""

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def strip_member_email(cls, value: object) -> object:
        return strip_email_whitespace(value)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_member_email(cls, value: EmailStr) -> str:
        return normalize_email(value)


class GroupMemberResponse(BaseModel):
    """Schema phản hồi thông tin thành viên mới được thêm vào nhóm (không lộ password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    group_id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    full_name: str
    role: GroupRole
    joined_at: UTCDatetime


__all__ = [
    "GroupCreateRequest",
    "GroupMemberAddRequest",
    "GroupMemberResponse",
    "GroupResponse",
    "GroupRole",
]
