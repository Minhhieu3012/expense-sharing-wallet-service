import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.group import Group, GroupMember
from app.schemas.group import GroupCreateRequest, GroupRole
from app.services.group_service import create_group


def _build_mock_db() -> MagicMock:
    db = MagicMock()
    added_objects: list[object] = []
    db._added_objects = added_objects

    def fake_add(obj: object) -> None:
        added_objects.append(obj)

    def fake_refresh(obj: object) -> None:
        if isinstance(obj, Group):
            if obj.id is None:
                obj.id = uuid.uuid4()
            if obj.created_at is None:
                obj.created_at = datetime(2026, 11, 26, 7, 0, 0, tzinfo=timezone.utc)

    db.add.side_effect = fake_add
    db.refresh.side_effect = fake_refresh
    return db


def test_create_group_inserts_group_and_admin_membership_in_single_transaction() -> None:
    # Arrange
    db = _build_mock_db()
    creator_id = uuid.uuid4()
    payload = GroupCreateRequest(name="Chuyến đi Đà Lạt 2026")

    # Act
    result = create_group(db, creator_id, payload)

    # Assert: đúng 2 ORM objects (Group + GroupMember ADMIN) trong cùng 1 transaction
    assert len(db._added_objects) == 2
    created_group, created_member = db._added_objects
    assert isinstance(created_group, Group)
    assert isinstance(created_member, GroupMember)

    assert created_group.name == "Chuyến đi Đà Lạt 2026"
    assert created_group.description is None
    assert created_group.currency == "VND"
    assert created_group.created_by == creator_id

    assert created_member.group_id == created_group.id
    assert created_member.user_id == creator_id
    assert created_member.role == GroupRole.ADMIN.value

    db.flush.assert_called_once()
    db.commit.assert_called_once()
    db.rollback.assert_not_called()

    # Kiểm tra payload trả về chuẩn API contract
    dumped = result.model_dump(mode="json")
    assert dumped == {
        "id": str(created_group.id),
        "name": "Chuyến đi Đà Lạt 2026",
        "description": None,
        "currency": "VND",
        "created_by": str(creator_id),
        "role": "ADMIN",
        "created_at": "2026-11-26T07:00:00Z",
    }


def test_create_group_persists_custom_description_and_currency() -> None:
    # Arrange
    db = _build_mock_db()
    creator_id = uuid.uuid4()
    payload = GroupCreateRequest(
        name="Chuyến đi Singapore",
        description="Quỹ đi chơi cuối năm",
        currency="sgd",
    )

    # Act
    result = create_group(db, creator_id, payload)

    # Assert
    assert result.description == "Quỹ đi chơi cuối năm"
    assert result.currency == "SGD"
    assert result.role == GroupRole.ADMIN


def test_create_group_rolls_back_transaction_when_commit_or_member_insert_fails() -> None:
    # Arrange
    db = _build_mock_db()
    db.commit.side_effect = RuntimeError("Simulated DB error on group_members insert")
    creator_id = uuid.uuid4()
    payload = GroupCreateRequest(name="Nhóm lỗi transaction")

    # Act & Assert
    with pytest.raises(RuntimeError, match="Simulated DB error"):
        create_group(db, creator_id, payload)

    db.rollback.assert_called_once()
