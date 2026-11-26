import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.main import app
from app.models.group import Group, GroupMember
from app.models.user import User
from app.schemas.group import GroupMemberResponse, GroupResponse, GroupRole


def _make_user(email: str = "admin@example.com", full_name: str = "Admin") -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash="hashed",
        full_name=full_name,
    )


def test_group_endpoints_require_bearer_auth_and_return_401_without_token() -> None:
    client = TestClient(app)
    group_id = uuid.uuid4()
    user_id = uuid.uuid4()

    res_create = client.post("/api/v1/groups", json={"name": "Chuyến đi Đà Lạt"})
    res_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"email": "member@example.com"},
    )
    res_remove = client.delete(f"/api/v1/groups/{group_id}/members/{user_id}")

    for res in (res_create, res_add, res_remove):
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_post_groups_returns_201_created_with_admin_role() -> None:
    admin_user = _make_user()
    fake_db = MagicMock()

    def fake_refresh(obj: object) -> None:
        if isinstance(obj, Group):
            obj.created_at = datetime(2026, 11, 26, 10, 0, 0, tzinfo=timezone.utc)

    fake_db.refresh.side_effect = fake_refresh

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/groups",
            json={
                "name": "Chuyến đi Đà Lạt 2026",
                "description": "Quỹ chia tiền ăn uống và xe cộ",
                "currency": "VND",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert body["name"] == "Chuyến đi Đà Lạt 2026"
    assert body["description"] == "Quỹ chia tiền ăn uống và xe cộ"
    assert body["currency"] == "VND"
    assert body["created_by"] == str(admin_user.id)
    assert body["role"] == "ADMIN"
    assert body["created_at"] == "2026-11-26T10:00:00Z"


def test_post_group_member_returns_201_created_and_handles_business_errors() -> None:
    admin_user = _make_user()
    group_id = uuid.uuid4()
    new_member_id = uuid.uuid4()
    fake_db = MagicMock()

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    client = TestClient(app)

    expected_member = GroupMemberResponse(
        group_id=group_id,
        user_id=new_member_id,
        email="thanhvien2@example.com",
        full_name="Trần Thị B",
        role=GroupRole.MEMBER,
        joined_at=datetime(2026, 11, 26, 10, 30, 0, tzinfo=timezone.utc),
    )

    try:
        with patch("app.api.v1.groups.add_group_member", return_value=expected_member):
            res_201 = client.post(
                f"/api/v1/groups/{group_id}/members",
                json={"email": "thanhvien2@example.com"},
            )

        with patch(
            "app.api.v1.groups.add_group_member",
            side_effect=ForbiddenException(
                "Chỉ trưởng nhóm (ADMIN) mới có quyền thực hiện thao tác này.",
                code="GROUP_ADMIN_REQUIRED",
            ),
        ):
            res_403 = client.post(
                f"/api/v1/groups/{group_id}/members",
                json={"email": "thanhvien2@example.com"},
            )

        with patch(
            "app.api.v1.groups.add_group_member",
            side_effect=ConflictException(
                "Người dùng này đã là thành viên của nhóm.",
                code="MEMBER_ALREADY_IN_GROUP",
            ),
        ):
            res_409 = client.post(
                f"/api/v1/groups/{group_id}/members",
                json={"email": "thanhvien2@example.com"},
            )
    finally:
        app.dependency_overrides.clear()

    assert res_201.status_code == 201
    assert res_201.json() == {
        "group_id": str(group_id),
        "user_id": str(new_member_id),
        "email": "thanhvien2@example.com",
        "full_name": "Trần Thị B",
        "role": "MEMBER",
        "joined_at": "2026-11-26T10:30:00Z",
    }
    assert res_403.status_code == 403
    assert res_403.json()["error"]["code"] == "GROUP_ADMIN_REQUIRED"
    assert res_409.status_code == 409
    assert res_409.json()["error"]["code"] == "MEMBER_ALREADY_IN_GROUP"


def test_delete_group_member_returns_204_no_content_and_propagates_400_404() -> None:
    admin_user = _make_user()
    group_id = uuid.uuid4()
    target_user_id = uuid.uuid4()
    fake_db = MagicMock()

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    client = TestClient(app)

    try:
        with patch("app.api.v1.groups.remove_group_member", return_value=None):
            res_204 = client.delete(f"/api/v1/groups/{group_id}/members/{target_user_id}")

        with patch(
            "app.api.v1.groups.remove_group_member",
            side_effect=BadRequestException(
                "Không thể xóa thành viên khi vẫn còn công nợ chưa thanh toán trong nhóm.",
                code="MEMBER_HAS_UNSETTLED_DEBT",
                details={"user_id": str(target_user_id)},
            ),
        ):
            res_400 = client.delete(f"/api/v1/groups/{group_id}/members/{target_user_id}")

        with patch(
            "app.api.v1.groups.remove_group_member",
            side_effect=NotFoundException(
                "Thành viên không tồn tại trong nhóm chi tiêu này.",
                code="MEMBER_NOT_FOUND",
            ),
        ):
            res_404 = client.delete(f"/api/v1/groups/{group_id}/members/{target_user_id}")
    finally:
        app.dependency_overrides.clear()

    assert res_204.status_code == 204
    assert res_204.content == b""

    assert res_400.status_code == 400
    assert res_400.json()["error"]["code"] == "MEMBER_HAS_UNSETTLED_DEBT"

    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "MEMBER_NOT_FOUND"
