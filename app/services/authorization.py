from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.group import Group, GroupMember
from app.schemas.group import GroupRole


def get_group_membership(
    db: Session,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GroupMember | None:
    """Truy vấn bản ghi thành viên của một người dùng trong nhóm (khóa chính tổ hợp)."""
    return db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
    )


def require_group_member(
    db: Session,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GroupMember:
    """Xác minh người dùng đang là thành viên của nhóm (ngăn chặn IDOR theo BR-06, NFR-11).

    - Nhóm không tồn tại -> ném 404 Not Found (GROUP_NOT_FOUND).
    - Nhóm tồn tại nhưng người dùng không phải thành viên -> ném 403 Forbidden (GROUP_ACCESS_DENIED).
    - Hợp lệ -> trả về bản ghi GroupMember để tầng service tái sử dụng.
    """
    membership = get_group_membership(db, group_id, user_id)
    if membership is not None:
        return membership

    group_exists = db.scalar(select(Group.id).where(Group.id == group_id))
    if group_exists is None:
        raise NotFoundException(
            message="Không tìm thấy nhóm chi tiêu.",
            code="GROUP_NOT_FOUND",
            details={"group_id": str(group_id)},
        )

    raise ForbiddenException(
        message="Bạn không có quyền truy cập vào nhóm chi tiêu này.",
        code="GROUP_ACCESS_DENIED",
        details={"group_id": str(group_id)},
    )


def require_group_admin(
    db: Session,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GroupMember:
    """Xác minh người dùng là trưởng nhóm (ADMIN) của nhóm chi tiêu.

    - Kế thừa kiểm tra tồn tại nhóm (404) và quyền thành viên (403 GROUP_ACCESS_DENIED).
    - Nếu chỉ là MEMBER thường -> ném 403 Forbidden (GROUP_ADMIN_REQUIRED).
    """
    membership = require_group_member(db, group_id, user_id)
    if membership.role != GroupRole.ADMIN:
        raise ForbiddenException(
            message="Chỉ trưởng nhóm (ADMIN) mới có quyền thực hiện thao tác này.",
            code="GROUP_ADMIN_REQUIRED",
            details={"group_id": str(group_id)},
        )

    return membership


__all__ = [
    "get_group_membership",
    "require_group_admin",
    "require_group_member",
]
