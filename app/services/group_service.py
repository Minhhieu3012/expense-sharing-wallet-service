from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.models.expense import Expense, ExpenseSplit
from app.models.group import Group, GroupMember
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.common import format_money
from app.schemas.group import (
    GroupCreateRequest,
    GroupMemberAddRequest,
    GroupMemberResponse,
    GroupResponse,
    GroupRole,
)
from app.services.authorization import get_group_membership, require_group_admin


def _is_duplicate_group_member_error(exc: IntegrityError) -> bool:
    """Xác định IntegrityError do trùng khóa chính tổ hợp pk_group_members (group_id, user_id)."""
    orig = exc.orig
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name == "pk_group_members":
        return True

    pgcode = getattr(orig, "pgcode", None)
    message = str(orig) if orig is not None else str(exc)
    if pgcode == "23505" and "group_members" in message.lower():
        return True
    return "pk_group_members" in message


def create_group(
    db: Session,
    creator_user_id: uuid.UUID,
    payload: GroupCreateRequest,
) -> GroupResponse:
    """Tạo nhóm chi tiêu mới và gắn người khởi tạo làm ADMIN trong một Database Transaction duy nhất."""
    try:
        group = Group(
            id=uuid.uuid4(),
            name=payload.name,
            description=payload.description,
            currency=payload.currency,
            created_by=creator_user_id,
        )
        db.add(group)
        # Flush để ghi bản ghi groups trước nhằm thỏa khóa ngoại fk_group_members_group.
        db.flush()

        admin_membership = GroupMember(
            group_id=group.id,
            user_id=creator_user_id,
            role=GroupRole.ADMIN.value,
        )
        db.add(admin_membership)
        db.commit()
        db.refresh(group)
    except Exception:
        db.rollback()
        raise

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        currency=group.currency,
        created_by=group.created_by,
        role=GroupRole(admin_membership.role),
        created_at=group.created_at,
    )


def add_group_member(
    db: Session,
    group_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: GroupMemberAddRequest,
) -> GroupMemberResponse:
    """Thêm thành viên mới (role='MEMBER') vào nhóm qua email; chỉ ADMIN mới có quyền thực hiện."""
    # 1. Xác minh nhóm tồn tại (404) và người gọi là ADMIN (403).
    require_group_admin(db, group_id, actor_user_id)

    # 2. Chuẩn hóa email và kiểm tra tài khoản được mời có tồn tại không (404).
    normalized_email = str(payload.email).strip().lower()
    target_user = db.scalar(select(User).where(User.email == normalized_email))
    if target_user is None:
        raise NotFoundException(
            message="Không tìm thấy người dùng với email này trong hệ thống.",
            code="USER_NOT_FOUND",
            details={"email": normalized_email},
        )

    # 3. Kiểm tra người dùng đã có mặt trong nhóm chưa (409 Conflict).
    existing_membership = get_group_membership(db, group_id, target_user.id)
    if existing_membership is not None:
        raise ConflictException(
            message="Người dùng này đã là thành viên của nhóm.",
            code="MEMBER_ALREADY_IN_GROUP",
            details={
                "group_id": str(group_id),
                "user_id": str(target_user.id),
                "email": target_user.email,
            },
        )

    # 4. Chèn thành viên mới với role='MEMBER' và bắt race condition pk_group_members.
    try:
        membership = GroupMember(
            group_id=group_id,
            user_id=target_user.id,
            role=GroupRole.MEMBER.value,
        )
        db.add(membership)
        db.commit()
        db.refresh(membership)
    except IntegrityError as exc:
        db.rollback()
        if _is_duplicate_group_member_error(exc):
            raise ConflictException(
                message="Người dùng này đã là thành viên của nhóm.",
                code="MEMBER_ALREADY_IN_GROUP",
                details={
                    "group_id": str(group_id),
                    "user_id": str(target_user.id),
                    "email": target_user.email,
                },
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    return GroupMemberResponse(
        group_id=membership.group_id,
        user_id=target_user.id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=GroupRole(membership.role),
        joined_at=membership.joined_at,
    )


def get_member_unsettled_pairwise_debts(
    db: Session,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[tuple[uuid.UUID, Decimal]]:
    """Tính công nợ tay đôi ròng (Pairwise Net Debt - BR-08) chưa tất toán của một thành viên.

    Quy ước dấu của net_amount với từng đối tác (counterparty):
    - Dương (> 0.00): đối tác đang nợ user_id.
    - Âm (< 0.00): user_id đang nợ đối tác.
    Chỉ trả về các cặp có tổng ròng khác 0.00.
    """
    paid_for_others = (
        select(
            ExpenseSplit.user_id.label("counterparty_id"),
            ExpenseSplit.amount.label("delta"),
        )
        .join(Expense, ExpenseSplit.expense_id == Expense.id)
        .where(
            Expense.group_id == group_id,
            Expense.paid_by_user_id == user_id,
            ExpenseSplit.user_id != user_id,
        )
    )

    owed_to_others = (
        select(
            Expense.paid_by_user_id.label("counterparty_id"),
            (-ExpenseSplit.amount).label("delta"),
        )
        .join(Expense, ExpenseSplit.expense_id == Expense.id)
        .where(
            Expense.group_id == group_id,
            ExpenseSplit.user_id == user_id,
            Expense.paid_by_user_id != user_id,
        )
    )

    settled_from_others = select(
        Settlement.payer_user_id.label("counterparty_id"),
        (-Settlement.amount).label("delta"),
    ).where(
        Settlement.group_id == group_id,
        Settlement.payee_user_id == user_id,
        Settlement.payer_user_id != user_id,
    )

    settled_to_others = select(
        Settlement.payee_user_id.label("counterparty_id"),
        Settlement.amount.label("delta"),
    ).where(
        Settlement.group_id == group_id,
        Settlement.payer_user_id == user_id,
        Settlement.payee_user_id != user_id,
    )

    entries = union_all(
        paid_for_others,
        owed_to_others,
        settled_from_others,
        settled_to_others,
    ).subquery("member_pairwise_entries")

    net_sum_expr = func.sum(entries.c.delta)
    stmt = (
        select(
            entries.c.counterparty_id,
            net_sum_expr.label("net_amount"),
        )
        .group_by(entries.c.counterparty_id)
        .having(net_sum_expr != Decimal("0.00"))
    )

    rows = db.execute(stmt).all()
    return [(row[0], Decimal(row[1])) for row in rows if Decimal(row[1]) != Decimal("0.00")]


def remove_group_member(
    db: Session,
    group_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
) -> None:
    """Xóa thành viên khỏi nhóm (chỉ ADMIN) khi thành viên đã tất toán toàn bộ công nợ (BR-06)."""
    # 1. Xác minh nhóm tồn tại (404) và người gọi là ADMIN (403).
    require_group_admin(db, group_id, actor_user_id)

    # 2. Xác minh thành viên mục tiêu đang thuộc nhóm (404).
    target_membership = get_group_membership(db, group_id, target_user_id)
    if target_membership is None:
        raise NotFoundException(
            message="Thành viên không tồn tại trong nhóm chi tiêu này.",
            code="MEMBER_NOT_FOUND",
            details={
                "group_id": str(group_id),
                "user_id": str(target_user_id),
            },
        )

    # 3. Ngăn xóa trưởng nhóm duy nhất khiến nhóm mất quyền quản trị.
    if target_membership.role == GroupRole.ADMIN.value:
        other_admin_count = db.scalar(
            select(func.count())
            .select_from(GroupMember)
            .where(
                GroupMember.group_id == group_id,
                GroupMember.role == GroupRole.ADMIN.value,
                GroupMember.user_id != target_user_id,
            )
        )
        if not other_admin_count:
            raise BadRequestException(
                message="Không thể xóa trưởng nhóm duy nhất khỏi nhóm.",
                code="CANNOT_REMOVE_LAST_ADMIN",
                details={
                    "group_id": str(group_id),
                    "user_id": str(target_user_id),
                },
            )

    # 4. Kiểm tra công nợ ròng theo từng cặp trong nhóm (BR-06, BR-08).
    unsettled_debts = get_member_unsettled_pairwise_debts(db, group_id, target_user_id)
    if unsettled_debts:
        raise BadRequestException(
            message="Không thể xóa thành viên khi vẫn còn công nợ chưa thanh toán trong nhóm.",
            code="MEMBER_HAS_UNSETTLED_DEBT",
            details={
                "group_id": str(group_id),
                "user_id": str(target_user_id),
                "unsettled_balances": [
                    {
                        "counterparty_user_id": str(counterparty_id),
                        "net_amount": format_money(net_amount),
                    }
                    for counterparty_id, net_amount in unsettled_debts
                ],
            },
        )

    # 5. Xóa thành viên khỏi nhóm trong transaction.
    try:
        db.delete(target_membership)
        db.commit()
    except Exception:
        db.rollback()
        raise


__all__ = [
    "add_group_member",
    "create_group",
    "get_member_unsettled_pairwise_debts",
    "remove_group_member",
]
