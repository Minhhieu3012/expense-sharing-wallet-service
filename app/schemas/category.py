from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CategoryResponse(BaseModel):
    """Thông tin một danh mục chi tiêu chuẩn (khớp hợp đồng API mục 2.1)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class CategoryListResponse(BaseModel):
    """Cấu trúc phản hồi danh sách danh mục chi tiêu ({"items": [...]})."""

    items: list[CategoryResponse]


__all__ = [
    "CategoryListResponse",
    "CategoryResponse",
]
