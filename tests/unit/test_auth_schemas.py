import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
    WalletSummaryResponse,
)


def test_register_request_normalizes_email_and_full_name() -> None:
    # Act: kiểm tra cắt khoảng trắng/tab/newline hai đầu và chuẩn hóa email về chữ thường
    payload = RegisterRequest(
        email="  \tGuest.User@Example.COM \n ",
        password="StrongPassword@123",
        full_name="  Nguyễn Văn A  ",
    )

    # Assert
    assert payload.email == "guest.user@example.com"
    assert payload.password == "StrongPassword@123"
    assert payload.full_name == "Nguyễn Văn A"


@pytest.mark.parametrize(
    ("data", "expected_field"),
    [
        (
            {
                "email": "not-an-email",
                "password": "StrongPassword@123",
                "full_name": "Nguyễn Văn A",
            },
            "email",
        ),
        (
            {
                "email": "guest@example.com",
                "password": "short",
                "full_name": "Nguyễn Văn A",
            },
            "password",
        ),
        (
            {
                "email": "guest@example.com",
                "password": "        ",
                "full_name": "Nguyễn Văn A",
            },
            "password",
        ),
        (
            {
                "email": "guest@example.com",
                "password": "StrongPassword@123",
                "full_name": "   ",
            },
            "full_name",
        ),
        (
            {
                "email": "guest@example.com",
                "password": "StrongPassword@123",
                "full_name": "A" * 151,
            },
            "full_name",
        ),
    ],
)
def test_register_request_rejects_invalid_inputs(
    data: dict[str, str],
    expected_field: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(**data)

    error_fields = {err["loc"][0] for err in exc_info.value.errors()}
    assert expected_field in error_fields


def test_register_response_from_orm_hides_password_hash_and_formats_money_and_utc() -> None:
    # Arrange: mô phỏng ORM User (có password_hash & timezone +07:00) và ORM Wallet (Decimal('0'))
    user_id = uuid.UUID("550e8400-e29b-41d4-a716-446655440001")
    wallet_id = uuid.UUID("660e8400-e29b-41d4-a716-446655440001")
    vn_tz = timezone(timedelta(hours=7))

    user_orm = User(
        id=user_id,
        email="guest@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$secret$hash",
        full_name="Nguyễn Văn A",
        created_at=datetime(2026, 11, 18, 17, 0, 0, tzinfo=vn_tz),
    )
    wallet_orm = Wallet(
        id=wallet_id,
        user_id=user_id,
        balance=Decimal("0"),
        currency="VND",
    )

    # Act
    response = RegisterResponse(
        user=UserResponse.model_validate(user_orm),
        wallet=WalletSummaryResponse.model_validate(wallet_orm),
    )
    json_data = json.loads(response.model_dump_json())

    # Assert
    assert json_data == {
        "user": {
            "id": "550e8400-e29b-41d4-a716-446655440001",
            "email": "guest@example.com",
            "full_name": "Nguyễn Văn A",
            "created_at": "2026-11-18T10:00:00Z",
        },
        "wallet": {
            "id": "660e8400-e29b-41d4-a716-446655440001",
            "balance": "0.00",
            "currency": "VND",
        },
    }
    assert "password_hash" not in json_data["user"]
    assert "password" not in json_data["user"]
    assert isinstance(json_data["wallet"]["balance"], str)
    assert isinstance(response.wallet.balance, Decimal)


def test_wallet_summary_formats_various_decimal_balances_with_two_decimals() -> None:
    wallet_id = uuid.uuid4()

    for raw_balance, expected_str in [
        (Decimal("0.00"), "0.00"),
        (Decimal("-0.00"), "0.00"),
        (Decimal("150000"), "150000.00"),
        (Decimal("33333.3"), "33333.30"),
        (Decimal("123456.78"), "123456.78"),
    ]:
        wallet = WalletSummaryResponse(id=wallet_id, balance=raw_balance, currency="VND")
        dumped = wallet.model_dump(mode="json")
        assert dumped["balance"] == expected_str


def test_user_response_converts_naive_datetime_to_iso_8601_utc() -> None:
    user = UserResponse(
        id=uuid.uuid4(),
        email="naive@example.com",
        full_name="Naive Time User",
        created_at=datetime(2026, 11, 18, 10, 0, 0),
    )

    dumped = user.model_dump(mode="json")
    assert dumped["created_at"] == "2026-11-18T10:00:00Z"


def test_login_request_normalizes_email_and_rejects_invalid_inputs() -> None:
    payload = LoginRequest(
        email="  \tGuest@Example.COM \n ",
        password="StrongPassword@123",
    )
    assert payload.email == "guest@example.com"
    assert payload.password == "StrongPassword@123"

    for bad_data in [
        {"email": "invalid-email", "password": "StrongPassword@123"},
        {"email": "guest@example.com", "password": ""},
        {"email": "guest@example.com", "password": "   "},
    ]:
        with pytest.raises(ValidationError):
            LoginRequest(**bad_data)


def test_login_response_matches_api_contract() -> None:
    res = LoginResponse(
        access_token="eyJ.access.token",
        refresh_token="eyJ.refresh.token",
        expires_in=1800,
    )
    assert res.model_dump(mode="json") == {
        "access_token": "eyJ.access.token",
        "refresh_token": "eyJ.refresh.token",
        "token_type": "bearer",
        "expires_in": 1800,
    }


def test_refresh_token_request_and_stateless_response_match_api_contract() -> None:
    req = RefreshTokenRequest(refresh_token="  eyJ.valid.refresh  ")
    assert req.refresh_token == "eyJ.valid.refresh"

    with pytest.raises(ValidationError):
        RefreshTokenRequest(refresh_token="   ")

    res = RefreshTokenResponse(
        access_token="eyJ.new.access.token",
        expires_in=1800,
    )
    dumped = res.model_dump(mode="json")
    assert dumped == {
        "access_token": "eyJ.new.access.token",
        "token_type": "bearer",
        "expires_in": 1800,
    }
    assert "refresh_token" not in dumped
