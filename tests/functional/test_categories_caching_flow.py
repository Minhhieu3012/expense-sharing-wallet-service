import os
import subprocess
import sys
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models import User, Wallet

TEST_EMAIL_DOMAIN = "@categories-flow-test.example.com"

EXPECTED_DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("FOOD", "Ăn uống"),
    ("TRANSPORT", "Di chuyển"),
    ("ACCOMMODATION", "Lưu trú"),
    ("UTILITIES", "Hóa đơn & Tiện ích"),
    ("ENTERTAINMENT", "Giải trí"),
]


def _cleanup_test_users(engine: Engine) -> None:
    """Dọn dẹp users/wallets sinh ra bởi bộ test (không đụng tới bảng categories mặc định)."""
    with Session(engine) as session:
        user_ids = list(
            session.scalars(
                select(User.id).where(User.email.like(f"%{TEST_EMAIL_DOMAIN}"))
            ).all()
        )
        if user_ids:
            session.execute(delete(Wallet).where(Wallet.user_id.in_(user_ids)))
            session.execute(delete(User).where(User.id.in_(user_ids)))
            session.commit()


@pytest.fixture(scope="module")
def migrated_test_engine() -> Generator[Engine, None, None]:
    """Đảm bảo expense_test_db đã chạy đủ migrations (gồm 0002 seed 5 danh mục mặc định)."""
    env = os.environ.copy()
    env["ALEMBIC_DATABASE_URL"] = settings.TEST_DATABASE_URL

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
    )

    engine = create_engine(settings.TEST_DATABASE_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def categories_client(
    migrated_test_engine: Engine,
) -> Generator[TestClient, None, None]:
    """Ghi đè dependency get_db sang expense_test_db và dọn sạch tài khoản test."""
    _cleanup_test_users(migrated_test_engine)

    test_session_local = sessionmaker(
        bind=migrated_test_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        try:
            yield client
        finally:
            app.dependency_overrides.clear()
            _cleanup_test_users(migrated_test_engine)


def _get_auth_headers(client: TestClient, *, prefix: str) -> dict[str, str]:
    email = f"{prefix}{TEST_EMAIL_DOMAIN}"
    password = "StrongPassword@123"

    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Người Dùng Kiểm Thử Danh Mục",
        },
    )
    assert reg_res.status_code == 201

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_get_categories_without_token_returns_401_unauthorized(
    categories_client: TestClient,
) -> None:
    # Act: gọi không có token (kể cả khi gửi kèm If-None-Match: *)
    res_no_header = categories_client.get("/api/v1/categories")
    res_with_inm = categories_client.get(
        "/api/v1/categories",
        headers={"If-None-Match": "*"},
    )

    # Assert: luôn bị chặn 401 Unauthorized đúng cấu trúc lỗi chuẩn
    for res in (res_no_header, res_with_inm):
        assert res.status_code == 401
        body = res.json()
        assert set(body.keys()) == {"error"}
        assert set(body["error"].keys()) == {"code", "message", "details"}
        assert body["error"]["code"] == "UNAUTHORIZED"


def test_get_categories_first_call_returns_200_with_5_categories_and_cache_headers(
    categories_client: TestClient,
) -> None:
    # Arrange
    auth_headers = _get_auth_headers(categories_client, prefix="cat.first")

    # Act
    response = categories_client.get("/api/v1/categories", headers=auth_headers)

    # Assert: 200 OK kèm đủ Cache-Control, ETag chuẩn HTTP và đủ 5 danh mục mặc định
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "public, max-age=3600"
    etag = response.headers.get("etag")
    assert etag is not None
    assert etag.startswith('"') and etag.endswith('"')

    body = response.json()
    assert set(body.keys()) == {"items"}
    items = body["items"]
    assert len(items) == 5

    # Xác nhận thứ tự id ASC và đầy đủ trường id, code, name (không thừa created_at)
    ids = [item["id"] for item in items]
    assert ids == sorted(ids)
    for item in items:
        assert set(item.keys()) == {"id", "code", "name"}

    assert [(item["code"], item["name"]) for item in items] == EXPECTED_DEFAULT_CATEGORIES


def test_get_categories_with_matching_if_none_match_returns_304_empty_body(
    categories_client: TestClient,
) -> None:
    # Arrange: gọi lần đầu để lấy ETag hiện tại từ PostgreSQL
    auth_headers = _get_auth_headers(categories_client, prefix="cat.304")
    first_res = categories_client.get("/api/v1/categories", headers=auth_headers)
    assert first_res.status_code == 200
    current_etag = first_res.headers["etag"]

    # Act: gọi lần sau kèm If-None-Match khớp chính xác, weak ETag, và danh sách ETag
    res_exact = categories_client.get(
        "/api/v1/categories",
        headers={**auth_headers, "If-None-Match": current_etag},
    )
    res_weak = categories_client.get(
        "/api/v1/categories",
        headers={**auth_headers, "If-None-Match": f"W/{current_etag}"},
    )
    res_list = categories_client.get(
        "/api/v1/categories",
        headers={**auth_headers, "If-None-Match": f'"old-etag", {current_etag}'},
    )

    # Assert: đều trả về 304 Not Modified không kèm body và giữ đúng 2 header caching
    for res in (res_exact, res_weak, res_list):
        assert res.status_code == 304
        assert res.content == b""
        assert res.headers.get("cache-control") == "public, max-age=3600"
        assert res.headers.get("etag") == current_etag


def test_get_categories_with_stale_or_wrong_if_none_match_returns_200_full_payload(
    categories_client: TestClient,
) -> None:
    # Arrange
    auth_headers = _get_auth_headers(categories_client, prefix="cat.stale")
    first_res = categories_client.get("/api/v1/categories", headers=auth_headers)
    assert first_res.status_code == 200
    current_etag = first_res.headers["etag"]

    # Act: gửi If-None-Match cũ/sai
    stale_res = categories_client.get(
        "/api/v1/categories",
        headers={**auth_headers, "If-None-Match": '"cat-v1-outdated00000000"'},
    )

    # Assert: trả về 200 OK kèm đầy đủ 5 danh mục và ETag mới nhất
    assert stale_res.status_code == 200
    assert stale_res.headers.get("cache-control") == "public, max-age=3600"
    assert stale_res.headers.get("etag") == current_etag
    items = stale_res.json()["items"]
    assert len(items) == 5
    assert [(item["code"], item["name"]) for item in items] == EXPECTED_DEFAULT_CATEGORIES
