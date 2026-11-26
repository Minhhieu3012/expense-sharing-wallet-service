import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.group import Group, GroupMember
from app.models.user import User
from app.schemas.group import GroupCreateRequest, GroupMemberAddRequest, GroupRole
from app.services.group_service import (
    add_group_member,
    create_group,
    get_member_unsettled_pairwise_debts,
    remove_group_member,
)


def _build_mock_db() -> MagicMock:
    db = MagicMock()
    added_objects: list[object] = []
    db._added_objects = added_objects

    def fake_add(obj: object) -> None:
        added_objects.append(obj)

    def fake_refresh(obj: object) -> None:
        now = datetime(2026, 11, 26, 7, 0, 0, tzinfo=timezone.utc)
        if isinstance(obj, Group):
            if obj.id is None:
                obj.id = uuid.uuid4()
            if obj.created_at is None:
                obj.created_at = now
        elif isinstance(obj, GroupMember):
            if obj.joined_at is None:
                obj.joined_at = now

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


def test_add_group_member_succeeds_for_admin_and_assigns_member_role() -> None:
    # Arrange
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    invited_user_id = uuid.uuid4()

    admin_membership = GroupMember(
        group_id=group_id,
        user_id=admin_id,
        role=GroupRole.ADMIN.value,
    )
    invited_user = User(
        id=invited_user_id,
        email="thanhvien2@example.com",
        password_hash="hashed",
        full_name="Trần Thị B",
    )

    db = _build_mock_db()
    # Thứ tự scalar: 1) require_group_admin -> admin_membership,
    #                2) tìm User theo email -> invited_user,
    #                3) get_group_membership(target) -> None
    db.scalar.side_effect = [admin_membership, invited_user, None]

    # Act
    result = add_group_member(
        db,
        group_id,
        admin_id,
        GroupMemberAddRequest(email="  ThanhVien2@Example.COM  "),
    )

    # Assert
    assert len(db._added_objects) == 1
    created_member = db._added_objects[0]
    assert isinstance(created_member, GroupMember)
    assert created_member.group_id == group_id
    assert created_member.user_id == invited_user_id
    assert created_member.role == GroupRole.MEMBER.value

    db.commit.assert_called_once()
    db.rollback.assert_not_called()

    assert result.model_dump(mode="json") == {
        "group_id": str(group_id),
        "user_id": str(invited_user_id),
        "email": "thanhvien2@example.com",
        "full_name": "Trần Thị B",
        "role": "MEMBER",
        "joined_at": "2026-11-26T07:00:00Z",
    }


def test_add_group_member_raises_403_when_caller_is_regular_member_or_outsider() -> None:
    group_id = uuid.uuid4()
    payload = GroupMemberAddRequest(email="invitee@example.com")

    # Case 1: người gọi là MEMBER thường -> 403 GROUP_ADMIN_REQUIRED
    db_member = _build_mock_db()
    member_id = uuid.uuid4()
    db_member.scalar.return_value = GroupMember(
        group_id=group_id, user_id=member_id, role=GroupRole.MEMBER.value
    )
    with pytest.raises(ForbiddenException) as exc_member:
        add_group_member(db_member, group_id, member_id, payload)
    assert exc_member.value.status_code == 403
    assert exc_member.value.code == "GROUP_ADMIN_REQUIRED"
    db_member.add.assert_not_called()

    # Case 2: người gọi không thuộc nhóm (IDOR) -> 403 GROUP_ACCESS_DENIED
    db_outsider = _build_mock_db()
    db_outsider.scalar.side_effect = [None, group_id]
    with pytest.raises(ForbiddenException) as exc_outsider:
        add_group_member(db_outsider, group_id, uuid.uuid4(), payload)
    assert exc_outsider.value.status_code == 403
    assert exc_outsider.value.code == "GROUP_ACCESS_DENIED"
    db_outsider.add.assert_not_called()


def test_add_group_member_raises_404_when_group_or_invited_email_not_found() -> None:
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    payload = GroupMemberAddRequest(email="missing@example.com")

    # Case 1: nhóm không tồn tại -> 404 GROUP_NOT_FOUND
    db_no_group = _build_mock_db()
    db_no_group.scalar.side_effect = [None, None]
    with pytest.raises(NotFoundException) as exc_group:
        add_group_member(db_no_group, group_id, admin_id, payload)
    assert exc_group.value.status_code == 404
    assert exc_group.value.code == "GROUP_NOT_FOUND"

    # Case 2: nhóm có tồn tại & người gọi là ADMIN, nhưng email chưa đăng ký -> 404 USER_NOT_FOUND
    db_no_user = _build_mock_db()
    admin_membership = GroupMember(
        group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN.value
    )
    db_no_user.scalar.side_effect = [admin_membership, None]
    with pytest.raises(NotFoundException) as exc_user:
        add_group_member(db_no_user, group_id, admin_id, payload)
    assert exc_user.value.status_code == 404
    assert exc_user.value.code == "USER_NOT_FOUND"
    assert exc_user.value.details == {"email": "missing@example.com"}


def test_add_group_member_raises_409_when_user_already_in_group() -> None:
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    existing_user_id = uuid.uuid4()

    admin_membership = GroupMember(
        group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN.value
    )
    existing_user = User(
        id=existing_user_id,
        email="already@example.com",
        password_hash="hashed",
        full_name="Đã Có Trong Nhóm",
    )
    existing_membership = GroupMember(
        group_id=group_id, user_id=existing_user_id, role=GroupRole.MEMBER.value
    )

    db = _build_mock_db()
    db.scalar.side_effect = [admin_membership, existing_user, existing_membership]

    with pytest.raises(ConflictException) as exc_info:
        add_group_member(
            db,
            group_id,
            admin_id,
            GroupMemberAddRequest(email="already@example.com"),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "MEMBER_ALREADY_IN_GROUP"
    assert exc_info.value.details == {
        "group_id": str(group_id),
        "user_id": str(existing_user_id),
        "email": "already@example.com",
    }
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_add_group_member_rolls_back_and_raises_409_on_concurrent_pk_violation() -> None:
    # Giả lập 2 request cùng thêm 1 thành viên tại cùng mili-giây -> chạm pk_group_members
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    invited_user_id = uuid.uuid4()

    admin_membership = GroupMember(
        group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN.value
    )
    invited_user = User(
        id=invited_user_id,
        email="race.member@example.com",
        password_hash="hashed",
        full_name="Race Member",
    )

    db = _build_mock_db()
    db.scalar.side_effect = [admin_membership, invited_user, None]
    orig_err = Exception(
        'duplicate key value violates unique constraint "pk_group_members"'
    )
    db.commit.side_effect = IntegrityError("INSERT INTO group_members ...", {}, orig_err)

    with pytest.raises(ConflictException) as exc_info:
        add_group_member(
            db,
            group_id,
            admin_id,
            GroupMemberAddRequest(email="race.member@example.com"),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "MEMBER_ALREADY_IN_GROUP"
    db.rollback.assert_called_once()


def test_add_group_member_rolls_back_and_reraises_other_errors() -> None:
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    invited_user = User(
        id=uuid.uuid4(),
        email="error.member@example.com",
        password_hash="hashed",
        full_name="Error Member",
    )
    admin_membership = GroupMember(
        group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN.value
    )

    # Non-PK IntegrityError
    db_integrity = _build_mock_db()
    db_integrity.scalar.side_effect = [admin_membership, invited_user, None]
    db_integrity.commit.side_effect = IntegrityError(
        "INSERT ...", {}, Exception("foreign key violation")
    )
    with pytest.raises(IntegrityError):
        add_group_member(
            db_integrity,
            group_id,
            admin_id,
            GroupMemberAddRequest(email="error.member@example.com"),
        )
    db_integrity.rollback.assert_called_once()

    # Unexpected RuntimeError
    db_runtime = _build_mock_db()
    db_runtime.scalar.side_effect = [admin_membership, invited_user, None]
    db_runtime.commit.side_effect = RuntimeError("DB connection dropped")
    with pytest.raises(RuntimeError, match="DB connection dropped"):
        add_group_member(
            db_runtime,
            group_id,
            admin_id,
            GroupMemberAddRequest(email="error.member@example.com"),
        )
    db_runtime.rollback.assert_called_once()


def test_get_member_unsettled_pairwise_debts_compiles_valid_postgresql_sql() -> None:
    group_id = uuid.uuid4()
    user_id = uuid.uuid4()
    counterparty_id = uuid.uuid4()

    db = MagicMock()
    db.execute.return_value.all.return_value = [
        (counterparty_id, Decimal("-100000.00")),
    ]

    result = get_member_unsettled_pairwise_debts(db, group_id, user_id)

    assert result == [(counterparty_id, Decimal("-100000.00"))]
    stmt = db.execute.call_args.args[0]
    compiled_sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "UNION ALL" in compiled_sql
    assert "HAVING sum(" in compiled_sql


def test_remove_group_member_succeeds_when_admin_and_zero_unsettled_debt() -> None:
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    member_id = uuid.uuid4()

    admin_membership = GroupMember(
        group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN.value
    )
    target_membership = GroupMember(
        group_id=group_id, user_id=member_id, role=GroupRole.MEMBER.value
    )

    db = _build_mock_db()
    db.scalar.side_effect = [admin_membership, target_membership]
    db.execute.return_value.all.return_value = []

    remove_group_member(db, group_id, admin_id, member_id)

    db.delete.assert_called_once_with(target_membership)
    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_remove_group_member_blocks_400_when_member_has_unsettled_debt() -> None:
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    member_id = uuid.uuid4()
    creditor_id = uuid.uuid4()

    admin_membership = GroupMember(
        group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN.value
    )
    target_membership = GroupMember(
        group_id=group_id, user_id=member_id, role=GroupRole.MEMBER.value
    )

    db = _build_mock_db()
    db.scalar.side_effect = [admin_membership, target_membership]
    db.execute.return_value.all.return_value = [(creditor_id, Decimal("-100000.00"))]

    with pytest.raises(BadRequestException) as exc_info:
        remove_group_member(db, group_id, admin_id, member_id)

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "MEMBER_HAS_UNSETTLED_DEBT"
    assert exc_info.value.details == {
        "group_id": str(group_id),
        "user_id": str(member_id),
        "unsettled_balances": [
            {
                "counterparty_user_id": str(creditor_id),
                "net_amount": "-100000.00",
            }
        ],
    }
    db.delete.assert_not_called()
    db.commit.assert_not_called()


def test_remove_group_member_rejects_missing_member_and_last_admin() -> None:
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    missing_member_id = uuid.uuid4()
    admin_membership = GroupMember(
        group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN.value
    )

    # Case 1: thành viên mục tiêu không tồn tại trong nhóm -> 404 MEMBER_NOT_FOUND
    db_missing = _build_mock_db()
    db_missing.scalar.side_effect = [admin_membership, None]
    with pytest.raises(NotFoundException) as exc_404:
        remove_group_member(db_missing, group_id, admin_id, missing_member_id)
    assert exc_404.value.status_code == 404
    assert exc_404.value.code == "MEMBER_NOT_FOUND"

    # Case 2: xóa trưởng nhóm duy nhất -> 400 CANNOT_REMOVE_LAST_ADMIN
    db_last_admin = _build_mock_db()
    db_last_admin.scalar.side_effect = [admin_membership, admin_membership, 0]
    with pytest.raises(BadRequestException) as exc_admin:
        remove_group_member(db_last_admin, group_id, admin_id, admin_id)
    assert exc_admin.value.status_code == 400
    assert exc_admin.value.code == "CANNOT_REMOVE_LAST_ADMIN"


def test_remove_group_member_rolls_back_on_commit_error() -> None:
    group_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    member_id = uuid.uuid4()
    admin_membership = GroupMember(
        group_id=group_id, user_id=admin_id, role=GroupRole.ADMIN.value
    )
    target_membership = GroupMember(
        group_id=group_id, user_id=member_id, role=GroupRole.MEMBER.value
    )

    db = _build_mock_db()
    db.scalar.side_effect = [admin_membership, target_membership]
    db.execute.return_value.all.return_value = []
    db.commit.side_effect = RuntimeError("Delete commit failed")

    with pytest.raises(RuntimeError, match="Delete commit failed"):
        remove_group_member(db, group_id, admin_id, member_id)

    db.rollback.assert_called_once()
