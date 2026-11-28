from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import Category
from app.schemas.category import CategoryListResponse, CategoryResponse

CATEGORIES_ETAG_PREFIX = "cat-v1"
CATEGORIES_CACHE_CONTROL = "public, max-age=3600"


def generate_categories_etag(payload: CategoryListResponse) -> str:
    """Sinh ETag ổn định (bọc trong dấu ngoặc kép theo chuẩn RFC 9110) từ danh sách danh mục.

    Sử dụng JSON chuẩn hóa kết hợp SHA-256 thay cho hash() nội tại của Python
    để đảm bảo giá trị ETag không đổi qua mỗi lần khởi động lại tiến trình.
    """
    canonical_json = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical_json).hexdigest()[:16]
    return f'"{CATEGORIES_ETAG_PREFIX}-{digest}"'


def _strip_weak_prefix(etag: str) -> str:
    cleaned = etag.strip()
    if cleaned.startswith("W/"):
        return cleaned[2:].strip()
    return cleaned


def is_etag_match(if_none_match: str | None, current_etag: str) -> bool:
    """So khớp header If-None-Match với ETag hiện tại theo phép so sánh yếu (RFC 9110 §13.1.2)."""
    if not if_none_match or not if_none_match.strip():
        return False

    normalized_current = _strip_weak_prefix(current_etag)
    for raw_candidate in if_none_match.split(","):
        candidate = raw_candidate.strip()
        if not candidate:
            continue
        if candidate == "*":
            return True
        if _strip_weak_prefix(candidate) == normalized_current:
            return True
    return False


def list_categories_with_etag(db: Session) -> tuple[CategoryListResponse, str]:
    """Truy vấn toàn bộ danh mục sắp xếp cố định theo id ASC và trả về kèm ETag ổn định."""
    categories = db.scalars(select(Category).order_by(Category.id.asc())).all()
    payload = CategoryListResponse(
        items=[CategoryResponse.model_validate(cat) for cat in categories]
    )
    etag = generate_categories_etag(payload)
    return payload, etag


__all__ = [
    "CATEGORIES_CACHE_CONTROL",
    "CATEGORIES_ETAG_PREFIX",
    "generate_categories_etag",
    "is_etag_match",
    "list_categories_with_etag",
]
