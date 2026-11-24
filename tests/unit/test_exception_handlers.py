from decimal import Decimal
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    AppException,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.main import app, register_exception_handlers


class SamplePayload(BaseModel):
    amount: Decimal
    password: str

    @field_validator("amount")
    @classmethod
    def validate_positive_amount(cls, value: Decimal) -> Decimal:
        if value <= Decimal("0.00"):
            raise ValueError("Số tiền phải lớn hơn 0")
        return value


def _assert_error_envelope(
    response: Any,
    *,
    expected_status: int,
    expected_code: str,
) -> dict[str, Any]:
    """Kiểm chứng mã HTTP, Content-Type và cấu trúc chuẩn {'error': {'code', 'message', 'details'}}."""
    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")

    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == expected_code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"] != ""
    return body["error"]


def _create_test_app() -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/test/app-error-400")
    def raise_bad_request() -> None:
        raise BadRequestException(
            message="Số dư ví hiện tại không đủ để thực hiện giao dịch thanh toán nợ.",
            code="INSUFFICIENT_WALLET_BALANCE",
            details={
                "current_balance": "50000.00",
                "required_amount": "120000.00",
            },
        )

    @test_app.get("/test/app-error-401")
    def raise_unauthorized() -> None:
        raise UnauthorizedException(
            message="Token đã hết hạn.",
            code="TOKEN_EXPIRED",
        )

    @test_app.get("/test/app-error-403")
    def raise_forbidden() -> None:
        raise ForbiddenException(
            message="Bạn không phải thành viên của nhóm này.",
            code="GROUP_ACCESS_DENIED",
        )

    @test_app.get("/test/app-error-404")
    def raise_not_found() -> None:
        raise NotFoundException(
            message="Không tìm thấy nhóm chi tiêu.",
            code="GROUP_NOT_FOUND",
        )

    @test_app.get("/test/app-error-409")
    def raise_conflict() -> None:
        raise ConflictException(
            message="Email đã tồn tại trong hệ thống.",
            code="EMAIL_ALREADY_EXISTS",
            details={"email": "guest@example.com"},
        )

    @test_app.post("/test/validate")
    def validate_payload(payload: SamplePayload) -> dict[str, str]:
        return {"amount": str(payload.amount)}

    @test_app.get("/test/query")
    def validate_query(limit: int = Query(ge=1, le=100)) -> dict[str, int]:
        return {"limit": limit}

    @test_app.get("/test/http-401")
    def raise_http_exception() -> None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @test_app.get("/test/unhandled")
    def raise_unhandled_exception() -> None:
        raise RuntimeError("SECRET_DB_PASSWORD=super-secret-leak")

    return test_app


def test_main_app_registers_all_four_global_exception_handlers() -> None:
    assert AppException in app.exception_handlers
    assert RequestValidationError in app.exception_handlers
    assert StarletteHTTPException in app.exception_handlers
    assert Exception in app.exception_handlers


def test_404_unknown_route_on_main_app_returns_standard_error_envelope() -> None:
    # Arrange
    client = TestClient(app)

    # Act
    response = client.get("/api/v1/non-existent-endpoint")

    # Assert
    error = _assert_error_envelope(
        response,
        expected_status=404,
        expected_code="NOT_FOUND",
    )
    assert error["message"] == "Not Found"
    assert error["details"] is None


def test_405_method_not_allowed_on_main_app_returns_standard_error_envelope() -> None:
    # Arrange
    client = TestClient(app)

    # Act
    response = client.post("/health")

    # Assert
    error = _assert_error_envelope(
        response,
        expected_status=405,
        expected_code="METHOD_NOT_ALLOWED",
    )
    assert error["message"] == "Method Not Allowed"
    assert error["details"] is None


def test_400_business_error_returns_standard_error_envelope() -> None:
    # Arrange
    client = TestClient(_create_test_app())

    # Act
    response = client.get("/test/app-error-400")

    # Assert
    error = _assert_error_envelope(
        response,
        expected_status=400,
        expected_code="INSUFFICIENT_WALLET_BALANCE",
    )
    assert error["message"] == "Số dư ví hiện tại không đủ để thực hiện giao dịch thanh toán nợ."
    assert error["details"] == {
        "current_balance": "50000.00",
        "required_amount": "120000.00",
    }


def test_app_exception_subclasses_401_403_404_409_return_standard_error_envelope() -> None:
    # Arrange
    client = TestClient(_create_test_app())

    # Act & Assert
    error_401 = _assert_error_envelope(
        client.get("/test/app-error-401"),
        expected_status=401,
        expected_code="TOKEN_EXPIRED",
    )
    assert error_401["details"] is None

    error_403 = _assert_error_envelope(
        client.get("/test/app-error-403"),
        expected_status=403,
        expected_code="GROUP_ACCESS_DENIED",
    )
    assert error_403["details"] is None

    error_404 = _assert_error_envelope(
        client.get("/test/app-error-404"),
        expected_status=404,
        expected_code="GROUP_NOT_FOUND",
    )
    assert error_404["details"] is None

    error_409 = _assert_error_envelope(
        client.get("/test/app-error-409"),
        expected_status=409,
        expected_code="EMAIL_ALREADY_EXISTS",
    )
    assert error_409["details"] == {"email": "guest@example.com"}


def test_422_body_validation_error_returns_standard_envelope_without_leaking_input() -> None:
    # Arrange
    client = TestClient(_create_test_app())

    # Act: gửi số âm kích hoạt custom ValueError validator + kiểm tra không lộ password
    response = client.post(
        "/test/validate",
        json={"amount": "-100.00", "password": "MySecretPassword@123"},
    )

    # Assert
    error = _assert_error_envelope(
        response,
        expected_status=422,
        expected_code="VALIDATION_ERROR",
    )
    assert error["message"] == "Dữ liệu đầu vào không hợp lệ."
    assert isinstance(error["details"], list)
    assert len(error["details"]) == 1
    assert error["details"][0]["field"] == "body.amount"
    assert "Số tiền phải lớn hơn 0" in error["details"][0]["message"]
    assert "MySecretPassword@123" not in response.text


def test_422_missing_fields_and_invalid_query_param_return_standard_envelope() -> None:
    # Arrange
    client = TestClient(_create_test_app())

    # Act
    missing_body_res = client.post("/test/validate", json={})
    invalid_query_res = client.get("/test/query", params={"limit": "not-an-int"})

    # Assert
    body_error = _assert_error_envelope(
        missing_body_res,
        expected_status=422,
        expected_code="VALIDATION_ERROR",
    )
    missing_fields = {item["field"] for item in body_error["details"]}
    assert missing_fields == {"body.amount", "body.password"}

    query_error = _assert_error_envelope(
        invalid_query_res,
        expected_status=422,
        expected_code="VALIDATION_ERROR",
    )
    assert query_error["details"][0]["field"] == "query.limit"


def test_http_exception_handler_preserves_headers_and_standard_format() -> None:
    # Arrange
    client = TestClient(_create_test_app())

    # Act
    response = client.get("/test/http-401")

    # Assert
    assert response.headers.get("www-authenticate") == "Bearer"
    error = _assert_error_envelope(
        response,
        expected_status=401,
        expected_code="UNAUTHORIZED",
    )
    assert error["message"] == "Not authenticated"
    assert error["details"] is None


def test_500_unhandled_exception_returns_standard_envelope_without_leaking_details() -> None:
    # Arrange
    client = TestClient(_create_test_app(), raise_server_exceptions=False)

    # Act
    response = client.get("/test/unhandled")

    # Assert
    error = _assert_error_envelope(
        response,
        expected_status=500,
        expected_code="INTERNAL_SERVER_ERROR",
    )
    assert error["message"] == "Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau."
    assert error["details"] is None
    assert "SECRET_DB_PASSWORD" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


def test_500_unhandled_exception_on_main_app_returns_standard_envelope() -> None:
    # Arrange: giả lập lỗi không lường trước ngay trên app thực tế mà không mutate routes
    client = TestClient(app, raise_server_exceptions=False)
    with patch(
        "app.main.check_db_connection",
        side_effect=RuntimeError("INTERNAL_SECRET_CONNECTION_STRING"),
    ):
        # Act
        response = client.get("/health")

    # Assert
    error = _assert_error_envelope(
        response,
        expected_status=500,
        expected_code="INTERNAL_SERVER_ERROR",
    )
    assert error["details"] is None
    assert "INTERNAL_SECRET_CONNECTION_STRING" not in response.text
    assert "Traceback" not in response.text
