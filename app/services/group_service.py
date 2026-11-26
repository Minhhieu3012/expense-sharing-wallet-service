from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.group import Group, GroupMember
from app.schemas.group import GroupCreateRequest, GroupResponse, GroupRole


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


__all__ = ["create_group"]
