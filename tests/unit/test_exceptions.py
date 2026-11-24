import pytest

from app.core.exceptions import (
    AppException,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)


def test_app_exception_stores_all_fields_and_serializes_payload() -> None:
    # Arrange
    details = {
        "current_balance": "50000.00",
        "required_amount": "120000.00",
    }

    # Act
    exc = AppException(
        status_code=400,
        code="INSUFFICIENT_WALLET_BALANCE",
        message="Số dư ví hiện tại không đủ để thực hiện giao dịch thanh toán nợ.",
        details=details,
    )

    # Assert
    assert isinstance(exc, Exception)
    assert exc.status_code == 400
    assert exc.code == "INSUFFICIENT_WALLET_BALANCE"
    assert exc.message == "Số dư ví hiện tại không đủ để thực hiện giao dịch thanh toán nợ."
    assert exc.details == details
    assert str(exc) == exc.message
    assert exc.to_error_payload() == {
        "error": {
            "code": "INSUFFICIENT_WALLET_BALANCE",
            "message": "Số dư ví hiện tại không đủ để thực hiện giao dịch thanh toán nợ.",
            "details": details,
        }
    }


def test_app_exception_defaults_details_to_none() -> None:
    # Act
    exc = AppException(status_code=404, code="GROUP_NOT_FOUND", message="Không tìm thấy nhóm.")

    # Assert
    assert exc.details is None
    assert exc.to_error_payload() == {
        "error": {
            "code": "GROUP_NOT_FOUND",
            "message": "Không tìm thấy nhóm.",
            "details": None,
        }
    }


@pytest.mark.parametrize(
    ("exc_cls", "expected_status", "expected_default_code"),
    [
        (BadRequestException, 400, "BAD_REQUEST"),
        (UnauthorizedException, 401, "UNAUTHORIZED"),
        (ForbiddenException, 403, "FORBIDDEN"),
        (NotFoundException, 404, "NOT_FOUND"),
        (ConflictException, 409, "CONFLICT"),
    ],
)
def test_business_exception_subclasses_have_expected_status_and_defaults(
    exc_cls: type[AppException],
    expected_status: int,
    expected_default_code: str,
) -> None:
    # Act
    exc = exc_cls("Thông báo lỗi mẫu")

    # Assert
    assert isinstance(exc, AppException)
    assert exc.status_code == expected_status
    assert exc.code == expected_default_code
    assert exc.message == "Thông báo lỗi mẫu"
    assert exc.details is None


def test_business_exception_subclass_accepts_custom_code_and_details() -> None:
    # Act
    exc = ConflictException(
        message="Email đã được đăng ký.",
        code="EMAIL_ALREADY_EXISTS",
        details={"email": "guest@example.com"},
    )

    # Assert
    assert exc.status_code == 409
    assert exc.code == "EMAIL_ALREADY_EXISTS"
    assert exc.details == {"email": "guest@example.com"}
    assert "EMAIL_ALREADY_EXISTS" in repr(exc)
