from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.category import CategoryListResponse
from app.services.category_service import (
    CATEGORIES_CACHE_CONTROL,
    is_etag_match,
    list_categories_with_etag,
)

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get(
    "",
    response_model=CategoryListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_304_NOT_MODIFIED: {
            "description": "Dữ liệu danh mục chưa thay đổi (If-None-Match khớp ETag hiện tại).",
        }
    },
    summary="Lấy danh sách danh mục chi tiêu chuẩn (hỗ trợ HTTP Caching với ETag)",
)
def get_categories_endpoint(
    response: Response,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryListResponse | Response:
    """Trả về danh mục chi tiêu chuẩn ([Auth: Bearer]) kèm Cache-Control và ETag (hỗ trợ 304 Not Modified)."""
    payload, etag = list_categories_with_etag(db)
    cache_headers = {
        "Cache-Control": CATEGORIES_CACHE_CONTROL,
        "ETag": etag,
    }

    if is_etag_match(if_none_match, etag):
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers=cache_headers,
        )

    response.headers.update(cache_headers)
    return payload
