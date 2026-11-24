import uuid
from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app
from app.models.user import User
from app.models.wallet import Wallet


def _make_fake_db(existing_user_id: uuid.UUID | None = None) -> MagicMock:
    db = MagicMock()
    db.scalar.return_value = existing_user_id

    def fake_refresh(obj: object) -> None:
        now = datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
        if isinstance(obj, User):
            if obj.id is None:
                obj.id = uuid.uuid4()
            if obj.created_at is None:
                obj.created_at = now
        elif isinstance(obj, Wallet):
            if obj.id is None:
                obj.id = uuid.uuid4()

    db.refresh.side_effect = fake_refresh
    return db


def test_post_register_returns_201_created_matching_api_contract() -> None:
    # Arrange
    fake_db = _make_fake_db(existing_user_id=None)

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        # Act: endpoint [Auth: Public], không gửi Authorization header
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "Guest@Example.com",
                "password": "StrongPassword@123",
                "full_name": "Nguyễn Văn A",
            },
        )
    finally:
        app.dependency_overrides.clear()

    # Assert
    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"user", "wallet"}

    user = body["user"]
    assert set(user.keys()) == {"id", "email", "full_name", "created_at"}
    uuid.UUID(user["id"])  # hợp lệ định dạng UUID
    assert user["email"] == "guest@example.com"
    assert user["full_name"] == "Nguyễn Văn A"
    assert user["created_at"] == "2026-11-18T10:00:00Z"
    assert "password_hash" not in user
    assert "StrongPassword@123" not in response.text

    wallet = body["wallet"]
    assert set(wallet.keys()) == {"id", "balance", "currency"}
    uuid.UUID(wallet["id"])
    assert wallet["balance"] == "0.00"
    assert wallet["currency"] == "VND"


def test_post_register_returns_409_when_email_exists() -> None:
    # Arrange
    fake_db = _make_fake_db(existing_user_id=uuid.uuid4())

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        # Act
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "guest@example.com",
                "password": "StrongPassword@123",
                "full_name": "Nguyễn Văn A",
            },
        )
    finally:
        app.dependency_overrides.clear()

    # Assert
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "EMAIL_ALREADY_EXISTS",
            "message": "Email đã được sử dụng trong hệ thống.",
            "details": {"email": "guest@example.com"},
        }
    }


def test_post_register_returns_422_on_invalid_payload_without_leaking_password() -> None:
    # Arrange
    client = TestClient(app)

    # Act
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "invalid-email",
            "password": "123",
            "full_name": "   ",
        },
    )

    # Assert
    assert response.status_code == 422
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "VALIDATION_ERROR"
    fields = {item["field"] for item in body["error"]["details"]}
    assert fields == {"body.email", "body.password", "body.full_name"}
    assert "123" not in str(body["error"]["details"])
