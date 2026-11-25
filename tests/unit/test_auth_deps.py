import uuid
from collections.abc import Generator
from datetime import timedelta
from unittest.mock import MagicMock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.jwt import create_access_token, create_refresh_token
from app.main import register_exception_handlers
from app.models.user import User


def _build_protected_test_app(db_user: User | None) -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    fake_db = MagicMock()
    fake_db.scalar.return_value = db_user

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield fake_db

    test_app.dependency_overrides[get_db] = override_get_db

    @test_app.get("/protected")
    def protected_route(current_user: User = Depends(get_current_user)) -> dict[str, str]:
        return {
            "id": str(current_user.id),
            "email": current_user.email,
            "full_name": current_user.full_name,
        }

    return test_app


def _assert_401_error_envelope(response, expected_code: str) -> None:
    assert response.status_code == 401
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == expected_code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"] != ""


def test_get_current_user_returns_user_for_valid_bearer_access_token() -> None:
    # Arrange
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="guest@example.com",
        password_hash="hashed",
        full_name="Nguyễn Văn A",
    )
    access_token = create_access_token(user_id)
    client = TestClient(_build_protected_test_app(user))

    # Act
    response = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "email": "guest@example.com",
        "full_name": "Nguyễn Văn A",
    }


def test_get_current_user_returns_401_when_authorization_header_missing_or_invalid_scheme() -> None:
    client = TestClient(_build_protected_test_app(None))

    # Thiếu hoàn toàn header Authorization (không bị FastAPI trả nhầm 403)
    res_missing = client.get("/protected")
    _assert_401_error_envelope(res_missing, "UNAUTHORIZED")

    # Sai scheme (Basic thay vì Bearer)
    res_basic = client.get("/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    _assert_401_error_envelope(res_basic, "UNAUTHORIZED")

    # Bearer rỗng không có token
    res_empty = client.get("/protected", headers={"Authorization": "Bearer    "})
    _assert_401_error_envelope(res_empty, "UNAUTHORIZED")


def test_get_current_user_returns_401_for_invalid_signature_or_expired_token() -> None:
    user_id = uuid.uuid4()
    expired_token = create_access_token(user_id, expires_delta=timedelta(seconds=-5))
    client = TestClient(_build_protected_test_app(None))

    res_malformed = client.get(
        "/protected",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    _assert_401_error_envelope(res_malformed, "INVALID_TOKEN")

    res_expired = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    _assert_401_error_envelope(res_expired, "TOKEN_EXPIRED")


def test_get_current_user_rejects_refresh_token_with_401_invalid_token_type() -> None:
    # Arrange: gửi refresh_token vào header Authorization: Bearer -> bắt buộc từ chối 401
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="guest@example.com",
        password_hash="hashed",
        full_name="Nguyễn Văn A",
    )
    refresh_token = create_refresh_token(user_id)
    client = TestClient(_build_protected_test_app(user))

    # Act
    response = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )

    # Assert
    _assert_401_error_envelope(response, "INVALID_TOKEN_TYPE")


def test_get_current_user_returns_401_when_sub_invalid_or_user_deleted() -> None:
    # Case 1: sub không phải UUID hợp lệ
    bad_sub_token = create_access_token("not-a-uuid")
    client = TestClient(_build_protected_test_app(None))

    res_bad_sub = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {bad_sub_token}"},
    )
    _assert_401_error_envelope(res_bad_sub, "INVALID_TOKEN")

    # Case 2: token hợp lệ nhưng user không còn trong DB
    valid_token = create_access_token(uuid.uuid4())
    res_missing_user = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    _assert_401_error_envelope(res_missing_user, "UNAUTHORIZED")


def test_protected_endpoint_exposes_http_bearer_in_openapi_schema() -> None:
    test_app = _build_protected_test_app(None)
    schema = test_app.openapi()
    security_schemes = schema["components"]["securitySchemes"]
    assert "HTTPBearer" in security_schemes
    assert security_schemes["HTTPBearer"]["scheme"] == "bearer"
