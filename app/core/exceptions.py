from __future__ import annotations

from http import HTTPStatus
from typing import Any


class AppException(Exception):
    """Lớp ngoại lệ nền dùng chung cho toàn bộ lỗi nghiệp vụ ở tầng services/."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        self.status_code: int = int(status_code)
        self.code: str = code
        self.message: str = message
        self.details: dict[str, Any] | list[Any] | None = details
        super().__init__(message)

    def to_error_payload(self) -> dict[str, Any]:
        """Chuyển ngoại lệ sang cấu trúc JSON lỗi thống nhất theo API Contract."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"status_code={self.status_code}, "
            f"code={self.code!r}, "
            f"message={self.message!r}, "
            f"details={self.details!r})"
        )


class BadRequestException(AppException):
    """Lỗi nghiệp vụ hoặc yêu cầu không hợp lệ (HTTP 400)."""

    def __init__(
        self,
        message: str,
        code: str = "BAD_REQUEST",
        details: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=HTTPStatus.BAD_REQUEST,
            code=code,
            message=message,
            details=details,
        )


class UnauthorizedException(AppException):
    """Lỗi chưa xác thực hoặc token không hợp lệ/hết hạn (HTTP 401)."""

    def __init__(
        self,
        message: str,
        code: str = "UNAUTHORIZED",
        details: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=HTTPStatus.UNAUTHORIZED,
            code=code,
            message=message,
            details=details,
        )


class ForbiddenException(AppException):
    """Lỗi không đủ quyền truy cập tài nguyên (HTTP 403)."""

    def __init__(
        self,
        message: str,
        code: str = "FORBIDDEN",
        details: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=HTTPStatus.FORBIDDEN,
            code=code,
            message=message,
            details=details,
        )


class NotFoundException(AppException):
    """Lỗi không tìm thấy tài nguyên (HTTP 404)."""

    def __init__(
        self,
        message: str,
        code: str = "NOT_FOUND",
        details: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=HTTPStatus.NOT_FOUND,
            code=code,
            message=message,
            details=details,
        )


class ConflictException(AppException):
    """Lỗi xung đột dữ liệu, ví dụ trùng email hoặc thành viên đã tồn tại (HTTP 409)."""

    def __init__(
        self,
        message: str,
        code: str = "CONFLICT",
        details: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=HTTPStatus.CONFLICT,
            code=code,
            message=message,
            details=details,
        )


__all__ = [
    "AppException",
    "BadRequestException",
    "ConflictException",
    "ForbiddenException",
    "NotFoundException",
    "UnauthorizedException",
]
