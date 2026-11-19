from collections.abc import AsyncIterator 
from contextlib import asynccontextmanager 

from fastapi import FastAPI, status 
from fastapi.responses import JSONResponse 

from app.core.config import settings 
from app.core.database import check_db_connection, engine 
from app.core.redis import check_redis_connection, redis_client

@asynccontextmanager 
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # quan ly vong doi resource: giai phong connection pool khi server tat. 
    yield
    engine.dispose()
    redis_client.close()

app = FastAPI (
    title = settings.APP_NAME,
    version = "0.1.0",
    lifespan = lifespan,
)

@app.get("/health", tags = ["Health"])
def health_check() -> JSONResponse:
    # Kiem tra connect status thuc te toi PostgreSQL va Redis.
    db_ok = check_db_connection()
    redis_ok = check_redis_connection()

    is_healthy = db_ok and redis_ok 
    http_status = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    payload = {
        "status": "ok" if is_healthy else "degraded",
        "dependencies": {
            "postgresql": "up" if db_ok else "down",
            "redis": "up" if redis_ok else "down",
        },
    }
    return JSONResponse(status_code = http_status, content = payload)