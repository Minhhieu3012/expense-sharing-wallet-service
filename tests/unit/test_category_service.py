from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.models.category import Category
from app.schemas.category import CategoryListResponse, CategoryResponse
from app.services.category_service import (
    generate_categories_etag,
    is_etag_match,
    list_categories_with_etag,
)


def test_list_categories_with_etag_orders_by_id_asc_and_returns_quoted_etag() -> None:
    # Arrange
    categories = [
        Category(id=1, code="FOOD", name="Ăn uống"),
        Category(id=2, code="TRANSPORT", name="Di chuyển"),
        Category(id=3, code="ACCOMMODATION", name="Lưu trú"),
        Category(id=4, code="UTILITIES", name="Hóa đơn & Tiện ích"),
        Category(id=5, code="ENTERTAINMENT", name="Giải trí"),
    ]
    db = MagicMock()
    db.scalars.return_value.all.return_value = categories

    # Act
    payload, etag = list_categories_with_etag(db)

    # Assert SQL có mệnh đề ORDER BY categories.id ASC
    stmt = db.scalars.call_args.args[0]
    compiled_sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ORDER BY categories.id ASC" in compiled_sql

    # Assert cấu trúc dữ liệu và định dạng ETag bọc dấu ngoặc kép theo chuẩn HTTP
    assert [item.code for item in payload.items] == [
        "FOOD",
        "TRANSPORT",
        "ACCOMMODATION",
        "UTILITIES",
        "ENTERTAINMENT",
    ]
    assert etag.startswith('"cat-v1-')
    assert etag.endswith('"')
    assert len(etag) == len('"cat-v1-"') + 16


def test_generate_categories_etag_is_deterministic_and_sensitive_to_changes() -> None:
    payload_a = CategoryListResponse(
        items=[
            CategoryResponse(id=1, code="FOOD", name="Ăn uống"),
            CategoryResponse(id=2, code="TRANSPORT", name="Di chuyển"),
        ]
    )
    payload_a_copy = CategoryListResponse(
        items=[
            CategoryResponse(id=1, code="FOOD", name="Ăn uống"),
            CategoryResponse(id=2, code="TRANSPORT", name="Di chuyển"),
        ]
    )
    payload_modified = CategoryListResponse(
        items=[
            CategoryResponse(id=1, code="FOOD", name="Ăn uống & Cafe"),
            CategoryResponse(id=2, code="TRANSPORT", name="Di chuyển"),
        ]
    )

    etag_1 = generate_categories_etag(payload_a)
    etag_2 = generate_categories_etag(payload_a_copy)
    etag_modified = generate_categories_etag(payload_modified)

    assert etag_1 == etag_2
    assert etag_1 != etag_modified


def test_is_etag_match_supports_exact_weak_list_and_wildcard() -> None:
    etag = '"cat-v1-0123456789abcdef"'

    assert is_etag_match(etag, etag) is True
    assert is_etag_match(f"W/{etag}", etag) is True
    assert is_etag_match(f'"old-etag", {etag}', etag) is True
    assert is_etag_match("*", etag) is True

    assert is_etag_match(None, etag) is False
    assert is_etag_match("   ", etag) is False
    assert is_etag_match('", "', etag) is False
    assert is_etag_match('"cat-v1-ffffffffffffffff"', etag) is False
