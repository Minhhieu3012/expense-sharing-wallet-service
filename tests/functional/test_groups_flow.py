import os
import subprocess
import sys
import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models import (
    Category,
    Expense,
    ExpenseSplit,
    Group,
    GroupMember,
    Settlement,
    User,
    Wallet,
)

TEST_EMAIL_DOMAIN = "@groups-flow-test.example.com"


def _cleanup_test_data(engine: Engine) -> None:
    """Dọn sạch dữ liệu test theo đúng thứ tự khóa ngoại ON DELETE RESTRICT."""
    with Session(engine) as session:
        user_ids = list(
            session.scalars(
                select(User.id).where(User.email.like(f"%{TEST_EMAIL_DOMAIN}"))
            ).all()
        )
        if not user_ids:
            return

        group_ids = list(
            session.scalars(
                select(Group.id).where(Group.created_by.in_(user_ids))
            ).all()
        )

        if group_ids:
            expense_ids = list(
                session.scalars(
                    select(Expense.id).where(Expense.group_id.in_(group_ids))
                ).all()
            )
            if expense_ids:
                session.execute(
                    delete(ExpenseSplit).where(ExpenseSplit.expense_id.in_(expense_ids))
                )
                session.execute(delete(Expense).where(Expense.id.in_(expense_ids)))

            session.execute(
                delete(Settlement).where(Settlement.group_id.in_(group_ids))
            )
            session.execute(
                delete(GroupMember).where(GroupMember.group_id.in_(group_ids))
            )
            session.execute(delete(Group).where(Group.id.in_(group_ids)))

        session.execute(delete(GroupMember).where(GroupMember.user_id.in_(user_ids)))
        session.execute(delete(Wallet).where(Wallet.user_id.in_(user_ids)))
        session.execute(delete(User).where(User.id.in_(user_ids)))
        session.commit()


def _assert_error_envelope(
    response: Any,
    *,
    expected_status: int,
    expected_code: str,
) -> dict[str, Any]:
    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == expected_code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"] != ""
    return body["error"]


@pytest.fixture(scope="module")
def migrated_test_engine() -> Generator[Engine, None, None]:
    """Đảm bảo expense_test_db đã chạy đủ migrations (gồm 5 categories mặc định)."""
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = settings.TEST_DATABASE_URL

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
    )

    engine = create_engine(settings.TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def groups_client(
    migrated_test_engine: Engine,
) -> Generator[tuple[TestClient, Engine], None, None]:
    """Ghi đè get_db sang expense_test_db và dọn sạch dữ liệu trước/sau mỗi test."""
    _cleanup_test_data(migrated_test_engine)

    test_session_local = sessionmaker(
        bind=migrated_test_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        try:
            yield client, migrated_test_engine
        finally:
            app.dependency_overrides.clear()
            _cleanup_test_data(migrated_test_engine)


def _register_and_login(
    client: TestClient,
    *,
    prefix: str,
    full_name: str,
    password: str = "StrongPassword@123",
) -> dict[str, Any]:
    email = f"{prefix}{TEST_EMAIL_DOMAIN}"
    reg_res = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert reg_res.status_code == 201
    user_id = reg_res.json()["user"]["id"]

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_res.status_code == 200
    access_token = login_res.json()["access_token"]

    return {
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "headers": {"Authorization": f"Bearer {access_token}"},
    }


def _create_group(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "Chuyến đi Đà Lạt 2026",
    description: str | None = "Quỹ chia tiền ăn uống và xe cộ",
    currency: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if description is not None:
        payload["description"] = description
    if currency is not None:
        payload["currency"] = currency

    res = client.post("/api/v1/groups", json=payload, headers=headers)
    assert res.status_code == 201
    return res.json()


# ============================================================================
# NHÓM 1: LUỒNG THÀNH CÔNG (TẠO NHÓM, THÊM & XÓA THÀNH VIÊN KHÔNG CÒN NỢ)
# ============================================================================


def test_create_group_add_and_remove_settled_member_happy_path(
    groups_client: tuple[TestClient, Engine],
) -> None:
    client, engine = groups_client
    admin = _register_and_login(client, prefix="happy.admin", full_name="Trưởng Nhóm A")
    member = _register_and_login(client, prefix="happy.member", full_name="Thành Viên B")

    # 1. Tạo nhóm (không truyền currency -> mặc định VND, vai trò ADMIN)
    group = _create_group(client, admin["headers"])
    group_id = group["id"]
    assert group["currency"] == "VND"
    assert group["created_by"] == admin["id"]
    assert group["role"] == "ADMIN"
    assert group["created_at"].endswith("Z")

    # 2. ADMIN thêm thành viên qua email có khoảng trắng & chữ hoa -> 201 Created
    add_res = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"email": f"  {member['email'].upper()}  "},
        headers=admin["headers"],
    )
    assert add_res.status_code == 201
    add_body = add_res.json()
    assert add_body["group_id"] == group_id
    assert add_body["user_id"] == member["id"]
    assert add_body["email"] == member["email"]
    assert add_body["full_name"] == member["full_name"]
    assert add_body["role"] == "MEMBER"
    assert add_body["joined_at"].endswith("Z")

    # Kiểm chứng dữ liệu thật trong PostgreSQL
    with Session(engine) as session:
        memberships = session.scalars(
            select(GroupMember).where(GroupMember.group_id == uuid.UUID(group_id))
        ).all()
        roles_by_user = {str(m.user_id): m.role for m in memberships}
        assert roles_by_user == {admin["id"]: "ADMIN", member["id"]: "MEMBER"}

    # 3. ADMIN xóa thành viên chưa phát sinh nợ -> 204 No Content
    del_res = client.delete(
        f"/api/v1/groups/{group_id}/members/{member['id']}",
        headers=admin["headers"],
    )
    assert del_res.status_code == 204
    assert del_res.content == b""

    with Session(engine) as session:
        remaining = session.scalars(
            select(GroupMember.user_id).where(GroupMember.group_id == uuid.UUID(group_id))
        ).all()
        assert [str(uid) for uid in remaining] == [admin["id"]]


# ============================================================================
# NHÓM 2: BẢO MẬT & PHÂN QUYỀN (IDOR 403 & MEMBER THƯỜNG 403)
# ============================================================================


def test_outsider_accessing_group_receives_403_idor_protection(
    groups_client: tuple[TestClient, Engine],
) -> None:
    client, engine = groups_client
    admin = _register_and_login(client, prefix="idor.admin", full_name="Admin")
    member = _register_and_login(client, prefix="idor.member", full_name="Member")
    outsider = _register_and_login(client, prefix="idor.outsider", full_name="Outsider")
    victim = _register_and_login(client, prefix="idor.victim", full_name="Victim")

    group = _create_group(client, admin["headers"])
    group_id = group["id"]
    assert (
        client.post(
            f"/api/v1/groups/{group_id}/members",
            json={"email": member["email"]},
            headers=admin["headers"],
        ).status_code
        == 201
    )

    # Người ngoài nhóm gọi thêm thành viên -> 403 GROUP_ACCESS_DENIED
    add_res = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"email": victim["email"]},
        headers=outsider["headers"],
    )
    _assert_error_envelope(
        add_res,
        expected_status=403,
        expected_code="GROUP_ACCESS_DENIED",
    )

    # Người ngoài nhóm gọi xóa thành viên -> 403 GROUP_ACCESS_DENIED
    del_res = client.delete(
        f"/api/v1/groups/{group_id}/members/{member['id']}",
        headers=outsider["headers"],
    )
    _assert_error_envelope(
        del_res,
        expected_status=403,
        expected_code="GROUP_ACCESS_DENIED",
    )

    # Xác nhận danh sách thành viên trong DB không hề bị thay đổi
    with Session(engine) as session:
        member_ids = {
            str(uid)
            for uid in session.scalars(
                select(GroupMember.user_id).where(
                    GroupMember.group_id == uuid.UUID(group_id)
                )
            ).all()
        }
        assert member_ids == {admin["id"], member["id"]}


def test_regular_member_calling_add_or_remove_receives_403_admin_required(
    groups_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = groups_client
    admin = _register_and_login(client, prefix="role.admin", full_name="Admin")
    member_1 = _register_and_login(client, prefix="role.m1", full_name="Member 1")
    member_2 = _register_and_login(client, prefix="role.m2", full_name="Member 2")
    candidate = _register_and_login(client, prefix="role.cand", full_name="Candidate")

    group = _create_group(client, admin["headers"])
    group_id = group["id"]
    for m in (member_1, member_2):
        assert (
            client.post(
                f"/api/v1/groups/{group_id}/members",
                json={"email": m["email"]},
                headers=admin["headers"],
            ).status_code
            == 201
        )

    # MEMBER thường gọi thêm thành viên -> 403 GROUP_ADMIN_REQUIRED
    add_res = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"email": candidate["email"]},
        headers=member_1["headers"],
    )
    _assert_error_envelope(
        add_res,
        expected_status=403,
        expected_code="GROUP_ADMIN_REQUIRED",
    )

    # MEMBER thường gọi xóa thành viên khác -> 403 GROUP_ADMIN_REQUIRED
    del_res = client.delete(
        f"/api/v1/groups/{group_id}/members/{member_2['id']}",
        headers=member_1["headers"],
    )
    _assert_error_envelope(
        del_res,
        expected_status=403,
        expected_code="GROUP_ADMIN_REQUIRED",
    )


# ============================================================================
# NHÓM 3: XUNG ĐỘT TRÙNG THÀNH VIÊN (409) & TÀI NGUYÊN KHÔNG TỒN TẠI (404)
# ============================================================================


def test_add_duplicate_member_and_concurrent_pk_violation_return_409(
    groups_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = groups_client
    admin = _register_and_login(client, prefix="dup.admin", full_name="Admin")
    member = _register_and_login(client, prefix="dup.member", full_name="Member")

    group = _create_group(client, admin["headers"])
    group_id = group["id"]

    first_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"email": member["email"]},
        headers=admin["headers"],
    )
    assert first_add.status_code == 201

    # Thêm trùng thành viên đã ở trong nhóm -> 409 MEMBER_ALREADY_IN_GROUP
    dup_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"email": member["email"].upper()},
        headers=admin["headers"],
    )
    _assert_error_envelope(
        dup_add,
        expected_status=409,
        expected_code="MEMBER_ALREADY_IN_GROUP",
    )

    # ADMIN tự thêm lại chính mình -> 409 MEMBER_ALREADY_IN_GROUP
    self_add = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"email": admin["email"]},
        headers=admin["headers"],
    )
    _assert_error_envelope(
        self_add,
        expected_status=409,
        expected_code="MEMBER_ALREADY_IN_GROUP",
    )

    # Race condition: vượt qua pre-check để chạm trực tiếp PK tổ hợp pk_group_members thật trên PostgreSQL
    with patch("app.services.group_service.get_group_membership", return_value=None):
        race_add = client.post(
            f"/api/v1/groups/{group_id}/members",
            json={"email": member["email"]},
            headers=admin["headers"],
        )
    _assert_error_envelope(
        race_add,
        expected_status=409,
        expected_code="MEMBER_ALREADY_IN_GROUP",
    )


def test_non_existent_group_email_or_member_return_404(
    groups_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = groups_client
    admin = _register_and_login(client, prefix="nf.admin", full_name="Admin")
    outsider = _register_and_login(client, prefix="nf.outsider", full_name="Outsider")

    group = _create_group(client, admin["headers"])
    group_id = group["id"]
    random_group_id = str(uuid.uuid4())

    # 1. Nhóm không tồn tại khi thêm thành viên -> 404 GROUP_NOT_FOUND
    res_add_no_group = client.post(
        f"/api/v1/groups/{random_group_id}/members",
        json={"email": outsider["email"]},
        headers=admin["headers"],
    )
    _assert_error_envelope(
        res_add_no_group,
        expected_status=404,
        expected_code="GROUP_NOT_FOUND",
    )

    # 2. Nhóm không tồn tại khi xóa thành viên -> 404 GROUP_NOT_FOUND
    res_del_no_group = client.delete(
        f"/api/v1/groups/{random_group_id}/members/{outsider['id']}",
        headers=admin["headers"],
    )
    _assert_error_envelope(
        res_del_no_group,
        expected_status=404,
        expected_code="GROUP_NOT_FOUND",
    )

    # 3. Email người được mời không tồn tại trong hệ thống -> 404 USER_NOT_FOUND
    res_no_email = client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"email": f"khong.ton.tai{TEST_EMAIL_DOMAIN}"},
        headers=admin["headers"],
    )
    _assert_error_envelope(
        res_no_email,
        expected_status=404,
        expected_code="USER_NOT_FOUND",
    )

    # 4. User không thuộc nhóm khi xóa -> 404 MEMBER_NOT_FOUND
    res_no_member = client.delete(
        f"/api/v1/groups/{group_id}/members/{outsider['id']}",
        headers=admin["headers"],
    )
    _assert_error_envelope(
        res_no_member,
        expected_status=404,
        expected_code="MEMBER_NOT_FOUND",
    )


# ============================================================================
# NHÓM 4: CHẶN XÓA THÀNH VIÊN CÒN NỢ (400 MEMBER_HAS_UNSETTLED_DEBT - BR-06/08)
# ============================================================================


def test_remove_member_with_unsettled_debt_returns_400_then_succeeds_after_settlement(
    groups_client: tuple[TestClient, Engine],
) -> None:
    client, engine = groups_client
    admin = _register_and_login(client, prefix="debt.admin", full_name="Chủ Nợ Admin")
    debtor = _register_and_login(client, prefix="debt.member", full_name="Người Nợ Member")

    group = _create_group(client, admin["headers"])
    group_uuid = uuid.UUID(group["id"])
    admin_uuid = uuid.UUID(admin["id"])
    debtor_uuid = uuid.UUID(debtor["id"])

    assert (
        client.post(
            f"/api/v1/groups/{group_uuid}/members",
            json={"email": debtor["email"]},
            headers=admin["headers"],
        ).status_code
        == 201
    )

    # Giả lập 1 khoản chi 200.000 VND do admin trả, chia đều 2 người -> debtor đang nợ admin 100.000 VND
    with Session(engine) as session:
        food_category_id = session.scalar(
            select(Category.id).where(Category.code == "FOOD")
        )
        assert food_category_id is not None

        expense = Expense(
            group_id=group_uuid,
            paid_by_user_id=admin_uuid,
            created_by_user_id=admin_uuid,
            category_id=food_category_id,
            title="Lẩu gà lá é",
            total_amount=Decimal("200000.00"),
            split_type="EQUAL",
            expense_date=datetime.now(timezone.utc),
        )
        session.add(expense)
        session.flush()

        session.add_all(
            [
                ExpenseSplit(
                    expense_id=expense.id,
                    user_id=admin_uuid,
                    amount=Decimal("100000.00"),
                ),
                ExpenseSplit(
                    expense_id=expense.id,
                    user_id=debtor_uuid,
                    amount=Decimal("100000.00"),
                ),
            ]
        )
        session.commit()

    # 1. Xóa khi còn nợ 100.000 VND -> bị chặn 400 MEMBER_HAS_UNSETTLED_DEBT
    res_blocked_full = client.delete(
        f"/api/v1/groups/{group_uuid}/members/{debtor_uuid}",
        headers=admin["headers"],
    )
    err_full = _assert_error_envelope(
        res_blocked_full,
        expected_status=400,
        expected_code="MEMBER_HAS_UNSETTLED_DEBT",
    )
    assert err_full["details"]["unsettled_balances"] == [
        {
            "counterparty_user_id": str(admin_uuid),
            "net_amount": "-100000.00",
        }
    ]

    # 2. Trả một phần 50.000 VND -> vẫn còn nợ 50.000 VND -> tiếp tục chặn 400
    with Session(engine) as session:
        session.add(
            Settlement(
                group_id=group_uuid,
                payer_user_id=debtor_uuid,
                payee_user_id=admin_uuid,
                amount=Decimal("50000.00"),
                note="Trả trước một nửa",
            )
        )
        session.commit()

    res_blocked_partial = client.delete(
        f"/api/v1/groups/{group_uuid}/members/{debtor_uuid}",
        headers=admin["headers"],
    )
    err_partial = _assert_error_envelope(
        res_blocked_partial,
        expected_status=400,
        expected_code="MEMBER_HAS_UNSETTLED_DEBT",
    )
    assert err_partial["details"]["unsettled_balances"] == [
        {
            "counterparty_user_id": str(admin_uuid),
            "net_amount": "-50000.00",
        }
    ]

    # 3. Trả nốt 50.000 VND -> công nợ ròng bằng 0.00 -> xóa thành công 204 No Content
    with Session(engine) as session:
        session.add(
            Settlement(
                group_id=group_uuid,
                payer_user_id=debtor_uuid,
                payee_user_id=admin_uuid,
                amount=Decimal("50000.00"),
                note="Tất toán phần còn lại",
            )
        )
        session.commit()

    res_deleted = client.delete(
        f"/api/v1/groups/{group_uuid}/members/{debtor_uuid}",
        headers=admin["headers"],
    )
    assert res_deleted.status_code == 204
    assert res_deleted.content == b""

    with Session(engine) as session:
        deleted_member = session.scalar(
            select(GroupMember).where(
                GroupMember.group_id == group_uuid,
                GroupMember.user_id == debtor_uuid,
            )
        )
        assert deleted_member is None


def test_remove_last_admin_is_blocked_with_400(
    groups_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = groups_client
    admin = _register_and_login(client, prefix="last.admin", full_name="Sole Admin")
    group = _create_group(client, admin["headers"])

    res = client.delete(
        f"/api/v1/groups/{group['id']}/members/{admin['id']}",
        headers=admin["headers"],
    )
    _assert_error_envelope(
        res,
        expected_status=400,
        expected_code="CANNOT_REMOVE_LAST_ADMIN",
    )
