import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.group import (
    GroupCreateRequest,
    GroupMemberAddRequest,
    GroupMemberResponse,
    GroupResponse,
    GroupRole,
)


def test_group_create_request_defaults_currency_to_vnd_and_normalizes_fields() -> None:
    # Act 1: bỏ qua currency và description -> mặc định currency="VND", description=None
    req_default = GroupCreateRequest(name="  Chuyến đi Đà Lạt 2026  ")
    assert req_default.name == "Chuyến đi Đà Lạt 2026"
    assert req_default.description is None
    assert req_default.currency == "VND"

    # Act 2: truyền currency chữ thường có khoảng trắng & description có khoảng trắng
    req_custom = GroupCreateRequest(
        name="  Quỹ đi Phú Quốc  ",
        description="  Quỹ chia tiền ăn uống và xe cộ  ",
        currency="  usd ",
    )
    assert req_custom.name == "Quỹ đi Phú Quốc"
    assert req_custom.description == "Quỹ chia tiền ăn uống và xe cộ"
    assert req_custom.currency == "USD"

    # Act 3: description chỉ có khoảng trắng -> chuẩn hóa thành None
    req_blank_desc = GroupCreateRequest(name="Nhóm ăn trưa", description="   ")
    assert req_blank_desc.description is None


@pytest.mark.parametrize(
    ("data", "expected_field"),
    [
        ({"name": "   "}, "name"),
        ({"name": "A" * 151}, "name"),
        ({"name": "Nhóm hợp lệ", "currency": "VN"}, "currency"),
        ({"name": "Nhóm hợp lệ", "currency": "VND1"}, "currency"),
        ({"name": "Nhóm hợp lệ", "currency": "123"}, "currency"),
        ({"name": "Nhóm hợp lệ", "currency": "VN$"}, "currency"),
    ],
)
def test_group_create_request_rejects_invalid_inputs(
    data: dict[str, str],
    expected_field: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        GroupCreateRequest(**data)

    error_fields = {err["loc"][0] for err in exc_info.value.errors()}
    assert expected_field in error_fields


def test_group_response_includes_admin_role_and_iso_utc_timestamp() -> None:
    # Arrange
    group_id = uuid.UUID("880e8400-e29b-41d4-a716-446655440010")
    creator_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440001")
    vn_tz = timezone(timedelta(hours=7))

    # Act
    response = GroupResponse(
        id=group_id,
        name="Chuyến đi Đà Lạt 2026",
        description="Quỹ chia tiền ăn uống và xe cộ",
        currency="VND",
        created_by=creator_id,
        role=GroupRole.ADMIN,
        created_at=datetime(2026, 11, 26, 17, 0, 0, tzinfo=vn_tz),
    )
    json_data = json.loads(response.model_dump_json())

    # Assert
    assert json_data == {
        "id": "880e8400-e29b-41d4-a716-446655440010",
        "name": "Chuyến đi Đà Lạt 2026",
        "description": "Quỹ chia tiền ăn uống và xe cộ",
        "currency": "VND",
        "created_by": "550e8400-e29b-41d4-a716-446655440001",
        "role": "ADMIN",
        "created_at": "2026-11-26T10:00:00Z",
    }


def test_group_member_add_request_normalizes_email_and_rejects_invalid_email() -> None:
    req = GroupMemberAddRequest(email="  \tThanhVien2@Example.COM \n ")
    assert req.email == "thanhvien2@example.com"

    with pytest.raises(ValidationError):
        GroupMemberAddRequest(email="not-an-email")


def test_group_member_response_serializes_member_info_with_utc_timestamp() -> None:
    group_id = uuid.UUID("880e8400-e29b-41d4-a716-446655440010")
    user_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440002")

    res = GroupMemberResponse(
        group_id=group_id,
        user_id=user_id,
        email="thanhvien2@example.com",
        full_name="Trần Thị B",
        role=GroupRole.MEMBER,
        joined_at=datetime(2026, 11, 26, 10, 30, 0, tzinfo=timezone.utc),
    )
    json_data = json.loads(res.model_dump_json())

    assert json_data == {
        "group_id": "880e8400-e29b-41d4-a716-446655440010",
        "user_id": "550e8400-e29b-41d4-a716-446655440002",
        "email": "thanhvien2@example.com",
        "full_name": "Trần Thị B",
        "role": "MEMBER",
        "joined_at": "2026-11-26T10:30:00Z",
    }
    assert "password_hash" not in json_data
