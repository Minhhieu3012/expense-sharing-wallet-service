from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.group import (
    GroupCreateRequest,
    GroupMemberAddRequest,
    GroupMemberResponse,
    GroupResponse,
)
from app.services.group_service import (
    add_group_member,
    create_group,
    remove_group_member,
)

router = APIRouter(prefix="/groups", tags=["Groups"])


@router.post(
    "",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo nhóm chi tiêu mới",
)
def create_group_endpoint(
    payload: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupResponse:
    """Tạo nhóm chi tiêu mới ([Auth: Bearer]) và gắn người khởi tạo làm ADMIN."""
    return create_group(
        db=db,
        creator_user_id=current_user.id,
        payload=payload,
    )


@router.post(
    "/{group_id}/members",
    response_model=GroupMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Thêm thành viên mới vào nhóm bằng email (Chỉ Group Admin)",
)
def add_group_member_endpoint(
    group_id: uuid.UUID,
    payload: GroupMemberAddRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupMemberResponse:
    """Thêm thành viên vào nhóm ([Auth: Bearer - Chỉ Group Admin]) với vai trò MEMBER."""
    return add_group_member(
        db=db,
        group_id=group_id,
        actor_user_id=current_user.id,
        payload=payload,
    )


@router.delete(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Xóa thành viên khỏi nhóm (Chỉ Group Admin)",
)
def remove_group_member_endpoint(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Xóa thành viên khỏi nhóm ([Auth: Bearer - Chỉ Group Admin]) khi không còn dư nợ."""
    remove_group_member(
        db=db,
        group_id=group_id,
        actor_user_id=current_user.id,
        target_user_id=user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
