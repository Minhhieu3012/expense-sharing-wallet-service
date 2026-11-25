import os
import subprocess
import sys
import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_current_user
from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    get_access_token_expires_in,
)
from app.main import register_exception_handlers
from app.models import User, Wallet

TEST_EMAIL_DOMAIN = "@jwt-flow-test.example.com"


def _cleanup_test_users(engine: Engine) -> None:
    """Dọn dẹp toàn bộ bản ghi users/wallets sinh ra bởi bộ test JWT flow."""
    with Session(engine) as session:
        user_ids = session.scalars(
            select(User.id).where(User.email.like(f"%{TEST_EMAIL_DOMAIN}"))
        ).all()
        if user_ids:
            session.execute(delete(Wallet).where(Wallet.user_id.in_(user_ids)))
            session.execute(delete(User).where(User.id.in_(user_ids)))
            session.commit()


def _assert_401_error_envelope(response: Any, expected_code: str) -> dict[str, Any]:
    """Xác minh mã 401 Unauthorized và cấu trúc JSON lỗi chuẩn {'error': {'code', 'message', 'details'}}."""
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == expected_code
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["message"] != ""
    return body["error"]


@pytest.fixture(scope="module")
def migrated_test_engine() -> Generator[Engine, None, None]:
    """Đảm bảo expense_test_db đã cập nhật đủ Alembic migrations trước khi chạy Functional Tests."""
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
def auth_flow_client(
    migrated_test_engine: Engine,
) -> Generator[TestClient, None, None]:
    """Client kiểm thử toàn trình dùng đúng router + exception handlers thật trên expense_test_db.

    Gắn thêm 1 endpoint bảo vệ bởi get_current_user (/api/v1/_test/me) trên app kiểm thử
    để xác minh toàn diện luồng xác thực Bearer mà không mutate routes của app chính.
    """
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

    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.include_router(api_router)

    @test_app.get("/api/v1/_test/me")
    def protected_me(
        current_user: User = Depends(get_current_user),
    ) -> dict[str, str]:
        return {
            "id": str(current_user.id),
            "email": current_user.email,
            "full_name": current_user.full_name,
        }

    test_app.dependency_overrides[get_db] = override_get_db

    with TestClient(test_app) as client:
        try:
            yield client
        finally:
            test_app.dependency_overrides.clear()
            _cleanup_test_users(migrated_test_engine)


def _register_account(
    client: TestClient,
    *,
    prefix: str,
    password: str = "StrongPassword@123",
    full_name: str = "Nguyễn Văn A",
) -> dict[str, Any]:
    email = f"{prefix}{TEST_EMAIL_DOMAIN}"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": full_name,
        },
    )
    assert response.status_code == 201
    return response.json()


# ============================================================================
# NHÓM 1: ĐĂNG NHẬP ĐÚNG / SAI MẬT KHẨU / SAI EMAIL
# ============================================================================


def test_login_success_issues_jwt_pair_and_authorizes_protected_endpoint(
    auth_flow_client: TestClient,
) -> None:
    # Arrange
    password = "StrongPassword@123"
    registered = _register_account(
        auth_flow_client,
        prefix="alice.login",
        password=password,
        full_name="Nguyễn Thị Alice",
    )
    user_id = registered["user"]["id"]
    email = registered["user"]["email"]

    # Act: đăng nhập với email có khoảng trắng & chữ hoa để kiểm tra chuẩn hóa
    login_res = auth_flow_client.post(
        "/api/v1/auth/login",
        json={
            "email": f"  {email.upper()}  ",
            "password": password,
        },
    )

    # Assert response 200 OK đúng hợp đồng API
    assert login_res.status_code == 200
    login_body = login_res.json()
    assert set(login_body.keys()) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
    }
    assert login_body["token_type"] == "bearer"
    assert login_body["expires_in"] == get_access_token_expires_in()

    access_claims = decode_access_token(login_body["access_token"])
    refresh_claims = decode_refresh_token(login_body["refresh_token"])
    assert access_claims["sub"] == user_id
    assert access_claims["token_type"] == "access"
    assert refresh_claims["sub"] == user_id
    assert refresh_claims["token_type"] == "refresh"

    # Dùng access_token vừa nhận gọi endpoint bảo vệ bởi get_current_user
    me_res = auth_flow_client.get(
        "/api/v1/_test/me",
        headers={"Authorization": f"Bearer {login_body['access_token']}"},
    )
    assert me_res.status_code == 200
    assert me_res.json() == {
        "id": user_id,
        "email": email,
        "full_name": "Nguyễn Thị Alice",
    }


def test_login_rejects_wrong_password_and_unknown_email_with_uniform_401(
    auth_flow_client: TestClient,
) -> None:
    # Arrange
    registered = _register_account(
        auth_flow_client,
        prefix="bob.wrongpass",
        password="CorrectPassword@123",
    )
    existing_email = registered["user"]["email"]

    # Act 1: đúng email nhưng sai mật khẩu
    wrong_pass_res = auth_flow_client.post(
        "/api/v1/auth/login",
        json={
            "email": existing_email,
            "password": "WrongPassword@999",
        },
    )

    # Act 2: email không tồn tại trong DB
    unknown_email_res = auth_flow_client.post(
        "/api/v1/auth/login",
        json={
            "email": f"does.not.exist{TEST_EMAIL_DOMAIN}",
            "password": "CorrectPassword@123",
        },
    )

    # Assert: cả 2 đều trả 401 đúng cấu trúc lỗi và cùng thông điệp (chống dò email)
    err_wrong_pass = _assert_401_error_envelope(wrong_pass_res, "INVALID_CREDENTIALS")
    err_unknown_email = _assert_401_error_envelope(
        unknown_email_res, "INVALID_CREDENTIALS"
    )
    assert err_wrong_pass["message"] == err_unknown_email["message"]
    assert err_wrong_pass["details"] is None


# ============================================================================
# NHÓM 2: LÀM MỚI TOKEN THÀNH CÔNG & CHẶN ACCESS_TOKEN / TOKEN LỖI Ở /refresh
# ============================================================================


def test_refresh_token_succeeds_and_new_access_token_authorizes_protected_endpoint(
    auth_flow_client: TestClient,
) -> None:
    # Arrange
    password = "StrongPassword@123"
    registered = _register_account(
        auth_flow_client,
        prefix="charlie.refresh",
        password=password,
        full_name="Trần Văn Charlie",
    )
    login_body = auth_flow_client.post(
        "/api/v1/auth/login",
        json={"email": registered["user"]["email"], "password": password},
    ).json()

    first_access_token = login_body["access_token"]
    refresh_token = login_body["refresh_token"]

    # Act 1: làm mới token lần 1
    refresh_res_1 = auth_flow_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    # Assert 1: trả 200 OK đúng thiết kế stateless (chỉ cấp access_token mới, không trả refresh_token)
    assert refresh_res_1.status_code == 200
    refresh_body_1 = refresh_res_1.json()
    assert set(refresh_body_1.keys()) == {"access_token", "token_type", "expires_in"}
    assert "refresh_token" not in refresh_body_1
    assert refresh_body_1["token_type"] == "bearer"
    assert refresh_body_1["expires_in"] == get_access_token_expires_in()
    assert refresh_body_1["access_token"] != first_access_token

    # Dùng access_token mới gọi qua get_current_user -> 200 OK
    me_res = auth_flow_client.get(
        "/api/v1/_test/me",
        headers={"Authorization": f"Bearer {refresh_body_1['access_token']}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["id"] == registered["user"]["id"]

    # Act 2: xác minh thiết kế stateless — refresh_token cũ vẫn tiếp tục dùng lại được cho tới hạn 7 ngày
    refresh_res_2 = auth_flow_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_res_2.status_code == 200
    assert refresh_res_2.json()["access_token"] != refresh_body_1["access_token"]


def test_refresh_endpoint_rejects_access_token_expired_wrong_sig_and_unknown_user_with_401(
    auth_flow_client: TestClient,
) -> None:
    # Arrange
    password = "StrongPassword@123"
    registered = _register_account(
        auth_flow_client,
        prefix="dave.refresh.fail",
        password=password,
    )
    user_id = registered["user"]["id"]
    login_body = auth_flow_client.post(
        "/api/v1/auth/login",
        json={"email": registered["user"]["email"], "password": password},
    ).json()

    now = datetime.now(timezone.utc)
    wrong_sig_refresh = jwt.encode(
        {
            "sub": user_id,
            "token_type": "refresh",
            "iat": now,
            "exp": now + timedelta(days=7),
        },
        key="wrong-secret-key-completely-different-from-env-32",
        algorithm=settings.JWT_ALGORITHM,
    )
    expired_refresh = create_refresh_token(user_id, expires_delta=timedelta(seconds=-5))
    deleted_user_refresh = create_refresh_token(uuid.uuid4())

    # Act & Assert 1: dùng access_token gọi /refresh -> 401 INVALID_TOKEN_TYPE
    res_access = auth_flow_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_body["access_token"]},
    )
    _assert_401_error_envelope(res_access, "INVALID_TOKEN_TYPE")

    # Act & Assert 2: refresh_token hết hạn -> 401 TOKEN_EXPIRED
    res_expired = auth_flow_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": expired_refresh},
    )
    _assert_401_error_envelope(res_expired, "TOKEN_EXPIRED")

    # Act & Assert 3: refresh_token sai chữ ký -> 401 INVALID_TOKEN
    res_wrong_sig = auth_flow_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": wrong_sig_refresh},
    )
    _assert_401_error_envelope(res_wrong_sig, "INVALID_TOKEN")

    # Act & Assert 4: refresh_token hợp lệ nhưng user không còn trong DB -> 401 UNAUTHORIZED
    res_missing_user = auth_flow_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": deleted_user_refresh},
    )
    _assert_401_error_envelope(res_missing_user, "UNAUTHORIZED")


# ============================================================================
# NHÓM 3: KIỂM CHỨNG get_current_user CHẶN 401 VỚI MỌI TOKEN KHÔNG HỢP LỆ
# ============================================================================


def test_get_current_user_rejects_refresh_token_expired_wrong_signature_and_missing_auth(
    auth_flow_client: TestClient,
) -> None:
    # Arrange
    password = "StrongPassword@123"
    registered = _register_account(
        auth_flow_client,
        prefix="eve.guard",
        password=password,
    )
    user_id = registered["user"]["id"]
    login_body = auth_flow_client.post(
        "/api/v1/auth/login",
        json={"email": registered["user"]["email"], "password": password},
    ).json()

    now = datetime.now(timezone.utc)
    expired_access = create_access_token(user_id, expires_delta=timedelta(seconds=-5))
    wrong_sig_access = jwt.encode(
        {
            "sub": user_id,
            "token_type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        key="wrong-secret-key-completely-different-from-env-32",
        algorithm=settings.JWT_ALGORITHM,
    )
    deleted_user_access = create_access_token(uuid.uuid4())

    # 1. Dùng refresh_token gắn vào Authorization: Bearer -> 401 INVALID_TOKEN_TYPE
    res_refresh_as_bearer = auth_flow_client.get(
        "/api/v1/_test/me",
        headers={"Authorization": f"Bearer {login_body['refresh_token']}"},
    )
    _assert_401_error_envelope(res_refresh_as_bearer, "INVALID_TOKEN_TYPE")

    # 2. Dùng access_token đã hết hạn -> 401 TOKEN_EXPIRED
    res_expired = auth_flow_client.get(
        "/api/v1/_test/me",
        headers={"Authorization": f"Bearer {expired_access}"},
    )
    _assert_401_error_envelope(res_expired, "TOKEN_EXPIRED")

    # 3. Dùng token sai chữ ký -> 401 INVALID_TOKEN
    res_wrong_sig = auth_flow_client.get(
        "/api/v1/_test/me",
        headers={"Authorization": f"Bearer {wrong_sig_access}"},
    )
    _assert_401_error_envelope(res_wrong_sig, "INVALID_TOKEN")

    # 4. Dùng token rác / sai định dạng -> 401 INVALID_TOKEN
    res_malformed = auth_flow_client.get(
        "/api/v1/_test/me",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    _assert_401_error_envelope(res_malformed, "INVALID_TOKEN")

    # 5. Thiếu header Authorization hoặc sai scheme -> 401 UNAUTHORIZED (không bị trả 403)
    res_missing = auth_flow_client.get("/api/v1/_test/me")
    _assert_401_error_envelope(res_missing, "UNAUTHORIZED")

    res_wrong_scheme = auth_flow_client.get(
        "/api/v1/_test/me",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    _assert_401_error_envelope(res_wrong_scheme, "UNAUTHORIZED")

    # 6. Access token hợp lệ nhưng tài khoản không còn tồn tại trong DB -> 401 UNAUTHORIZED
    res_deleted_user = auth_flow_client.get(
        "/api/v1/_test/me",
        headers={"Authorization": f"Bearer {deleted_user_access}"},
    )
    _assert_401_error_envelope(res_deleted_user, "UNAUTHORIZED")
