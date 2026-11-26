import uuid
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.group import GroupMember
from app.schemas.group import GroupRole
from app.services.authorization import (
    get_group_membership,
    require_group_admin,
    require_group_member,
)


def test_get_group_membership_returns_record_or_none() -> None:
    group_id = uuid.uuid4()
    user_id = uuid.uuid4()
    membership = GroupMember(group_id=group_id, user_id=user_id, role=GroupRole.MEMBER)

    db = MagicMock()
    db.scalar.return_value = membership
    assert get_group_membership(db, group_id, user_id) is membership

    db.scalar.return_value = None
    assert get_group_membership(db, group_id, user_id) is None


def test_require_group_member_succeeds_for_member_and_admin_with_single_query() -> None:
    group_id = uuid.uuid4()
    user_id = uuid.uuid4()

    for role in (GroupRole.MEMBER, GroupRole.ADMIN):
        membership = GroupMember(group_id=group_id, user_id=user_id, role=role)
        db = MagicMock()
        db.scalar.return_value = membership

        result = require_group_member(db, group_id, user_id)

        assert result is membership
        # Fast-path: thành viên hợp lệ chỉ tốn đúng 1 truy vấn lên pk_group_members
        assert db.scalar.call_count == 1


def test_require_group_member_raises_404_when_group_does_not_exist() -> None:
    group_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db = MagicMock()
    db.scalar.side_effect = [None, None]  # không có membership, và group không tồn tại

    with pytest.raises(NotFoundException) as exc_info:
        require_group_member(db, group_id, user_id)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "GROUP_NOT_FOUND"
    assert exc_info.value.details == {"group_id": str(group_id)}
    assert db.scalar.call_count == 2


def test_require_group_member_raises_403_when_non_member_accesses_existing_group() -> None:
    # Kịch bản IDOR: nhóm tồn tại nhưng caller không thuộc nhóm
    group_id = uuid.uuid4()
    outsider_id = uuid.uuid4()
    db = MagicMock()
    db.scalar.side_effect = [None, group_id]  # không có membership, nhưng group tồn tại

    with pytest.raises(ForbiddenException) as exc_info:
        require_group_member(db, group_id, outsider_id)

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "GROUP_ACCESS_DENIED"
    assert exc_info.value.details == {"group_id": str(group_id)}
    assert db.scalar.call_count == 2


def test_require_group_admin_succeeds_for_admin() -> None:
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    membership = GroupMember(group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN)
    db = MagicMock()
    db.scalar.return_value = membership

    result = require_group_admin(db, group_id, admin_id)

    assert result is membership
    assert result.role == GroupRole.ADMIN


def test_require_group_admin_raises_403_for_regular_member() -> None:
    group_id = uuid.uuid4()
    member_id = uuid.uuid4()
    membership = GroupMember(group_id=group_id, user_id=member_id, role=GroupRole.MEMBER)
    db = MagicMock()
    db.scalar.return_value = membership

    with pytest.raises(ForbiddenException) as exc_info:
        require_group_admin(db, group_id, member_id)

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "GROUP_ADMIN_REQUIRED"
    assert exc_info.value.details == {"group_id": str(group_id)}


def test_require_group_admin_propagates_404_and_403_for_non_member() -> None:
    group_id = uuid.uuid4()
    outsider_id = uuid.uuid4()

    # Nhóm không tồn tại -> 404 GROUP_NOT_FOUND
    db_missing = MagicMock()
    db_missing.scalar.side_effect = [None, None]
    with pytest.raises(NotFoundException) as exc_404:
        require_group_admin(db_missing, group_id, outsider_id)
    assert exc_404.value.code == "GROUP_NOT_FOUND"

    # Nhóm tồn tại nhưng outsider không thuộc nhóm -> 403 GROUP_ACCESS_DENIED
    db_outsider = MagicMock()
    db_outsider.scalar.side_effect = [None, group_id]
    with pytest.raises(ForbiddenException) as exc_403:
        require_group_admin(db_outsider, group_id, outsider_id)
    assert exc_403.value.code == "GROUP_ACCESS_DENIED"
