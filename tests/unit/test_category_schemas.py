import json
from datetime import datetime, timezone

from app.models.category import Category
from app.schemas.category import CategoryListResponse, CategoryResponse


def test_category_response_from_orm_exposes_only_id_code_name() -> None:
    # Arrange
    orm_category = Category(
        id=1,
        code="FOOD",
        name="Ăn uống",
        created_at=datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc),
    )

    # Act
    dto = CategoryResponse.model_validate(orm_category)
    dumped = dto.model_dump(mode="json")

    # Assert
    assert dumped == {"id": 1, "code": "FOOD", "name": "Ăn uống"}
    assert "created_at" not in dumped


def test_category_list_response_matches_api_contract() -> None:
    # Arrange
    orm_categories = [
        Category(id=1, code="FOOD", name="Ăn uống"),
        Category(id=2, code="TRANSPORT", name="Di chuyển"),
        Category(id=3, code="ACCOMMODATION", name="Lưu trú"),
        Category(id=4, code="UTILITIES", name="Hóa đơn & Tiện ích"),
        Category(id=5, code="ENTERTAINMENT", name="Giải trí"),
    ]

    # Act
    response = CategoryListResponse(
        items=[CategoryResponse.model_validate(cat) for cat in orm_categories]
    )
    json_data = json.loads(response.model_dump_json())

    # Assert
    assert json_data == {
        "items": [
            {"id": 1, "code": "FOOD", "name": "Ăn uống"},
            {"id": 2, "code": "TRANSPORT", "name": "Di chuyển"},
            {"id": 3, "code": "ACCOMMODATION", "name": "Lưu trú"},
            {"id": 4, "code": "UTILITIES", "name": "Hóa đơn & Tiện ích"},
            {"id": 5, "code": "ENTERTAINMENT", "name": "Giải trí"},
        ]
    }
