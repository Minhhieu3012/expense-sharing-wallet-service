import uuid
from collections.abc import Generator
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.category import Category
from app.models.user import User


def _make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="member@example.com",
        password_hash="hashed",
        full_name="Nguyễn Văn A",
    )


def _sample_categories() -> list[Category]:
    return [
        Category(id=1, code="FOOD", name="Ăn uống"),
        Category(id=2, code="TRANSPORT", name="Di chuyển"),
        Category(id=3, code="ACCOMMODATION", name="Lưu trú"),
        Category(id=4, code="UTILITIES", name="Hóa đơn & Tiện ích"),
        Category(id=5, code="ENTERTAINMENT", name="Giải trí"),
    ]


def test_get_categories_requires_bearer_auth_and_returns_401_without_token() -> None:
    client = TestClient(app)

    res = client.get(
        "/api/v1/categories",
        headers={"If-None-Match": "*"},
    )

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_get_categories_returns_200_with_cache_control_and_etag_headers() -> None:
    fake_db = MagicMock()
    fake_db.scalars.return_value.all.return_value = _sample_categories()

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _make_user
    client = TestClient(app)

    try:
        res = client.get("/api/v1/categories")
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert res.headers.get("cache-control") == "public, max-age=3600"
    etag = res.headers.get("etag")
    assert etag is not None
    assert etag.startswith('"cat-v1-') and etag.endswith('"')

    assert res.json() == {
        "items": [
            {"id": 1, "code": "FOOD", "name": "Ăn uống"},
            {"id": 2, "code": "TRANSPORT", "name": "Di chuyển"},
            {"id": 3, "code": "ACCOMMODATION", "name": "Lưu trú"},
            {"id": 4, "code": "UTILITIES", "name": "Hóa đơn & Tiện ích"},
            {"id": 5, "code": "ENTERTAINMENT", "name": "Giải trí"},
        ]
    }


def test_get_categories_returns_304_not_modified_with_empty_body_when_etag_matches() -> None:
    fake_db = MagicMock()
    fake_db.scalars.return_value.all.return_value = _sample_categories()

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _make_user
    client = TestClient(app)

    try:
        # Lần 1: lấy 200 OK cùng ETag
        first_res = client.get("/api/v1/categories")
        assert first_res.status_code == 200
        etag = first_res.headers["etag"]

        # Lần 2: gửi If-None-Match khớp chính xác -> 304 không body, vẫn giữ Cache-Control & ETag
        res_exact = client.get("/api/v1/categories", headers={"If-None-Match": etag})
        # Lần 3: gửi weak ETag W/"..." -> 304
        res_weak = client.get(
            "/api/v1/categories",
            headers={"If-None-Match": f"W/{etag}"},
        )
        # Lần 4: gửi ETag cũ không khớp -> trả 200 OK kèm đầy đủ payload
        res_stale = client.get(
            "/api/v1/categories",
            headers={"If-None-Match": '"cat-v1-stale00000000000"'},
        )
    finally:
        app.dependency_overrides.clear()

    for res_304 in (res_exact, res_weak):
        assert res_304.status_code == 304
        assert res_304.content == b""
        assert res_304.headers.get("cache-control") == "public, max-age=3600"
        assert res_304.headers.get("etag") == etag

    assert res_stale.status_code == 200
    assert len(res_stale.json()["items"]) == 5
    assert res_stale.headers.get("etag") == etag
