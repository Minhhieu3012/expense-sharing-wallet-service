import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.database import check_db_connection, engine
from app.core.exceptions import AppException
from app.core.redis import check_redis_connection, redis_client

logger = logging.getLogger(__name__)

HTTP_STATUS_ERROR_CODES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "VALIDATION_ERROR",
    status.HTTP_429_TOO_MANY_REQUESTS: "TOO_MANY_REQUESTS",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_SERVER_ERROR",
}


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | list[Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Tạo JSONResponse lỗi theo cấu trúc thống nhất của API Contract."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
        headers=headers,
    )


def register_exception_handlers(target_app: FastAPI) -> None:
    """Đăng ký Global Exception Handlers chuẩn hóa toàn bộ phản hồi lỗi."""

    @target_app.exception_handler(AppException)
    async def app_exception_handler(
        _request: Request, exc: AppException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_error_payload(),
        )

    @target_app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Chỉ trích xuất field/message/type để đảm bảo JSON-serializable và không lộ input nhạy cảm.
        validation_details = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ())),
                "message": err.get("msg", "Invalid value"),
                "type": err.get("type", "validation_error"),
            }
            for err in exc.errors()
        ]
        return build_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="VALIDATION_ERROR",
            message="Dữ liệu đầu vào không hợp lệ.",
            details=validation_details,
        )

    @target_app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        error_code = HTTP_STATUS_ERROR_CODES.get(
            exc.status_code, f"HTTP_{exc.status_code}"
        )
        if isinstance(exc.detail, str):
            message = exc.detail
            details: dict[str, Any] | list[Any] | None = None
        elif isinstance(exc.detail, (dict, list)):
            try:
                message = HTTPStatus(exc.status_code).phrase
            except ValueError:
                message = "HTTP Error"
            details = exc.detail
        else:
            message = str(exc.detail) if exc.detail is not None else "HTTP Error"
            details = None

        return build_error_response(
            status_code=exc.status_code,
            code=error_code,
            message=message,
            details=details,
            headers=exc.headers,
        )

    @target_app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, _exc: Exception
    ) -> JSONResponse:
        # Ghi log đầy đủ ở server, tuyệt đối không trả stack trace hay thông tin nội bộ ra client.
        logger.exception(
            "Lỗi hệ thống không lường trước khi xử lý %s %s",
            request.method,
            request.url.path,
        )
        return build_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.",
            details=None,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # quan ly vong doi resource: giai phong connection pool khi server tat.
    yield
    engine.dispose()
    redis_client.close()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)
register_exception_handlers(app)


@app.get("/health", tags=["Health"])
def health_check() -> JSONResponse:
    # Kiem tra connect status thuc te toi PostgreSQL va Redis.
    db_ok = check_db_connection()
    redis_ok = check_redis_connection()

    is_healthy = db_ok and redis_ok
    http_status = (
        status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    payload = {
        "status": "ok" if is_healthy else "degraded",
        "dependencies": {
            "postgresql": "up" if db_ok else "down",
            "redis": "up" if redis_ok else "down",
        },
    }
    return JSONResponse(status_code=http_status, content=payload)
