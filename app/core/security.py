from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Sử dụng Argon2id (khuyến nghị hàng đầu của OWASP) với salt ngẫu nhiên 16 bytes
# tự động sinh mới cho mỗi lần băm (chuỗi PHC: $argon2id$v=19$...).
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def hash_password(plain_password: str) -> str:
    """Băm mật khẩu một chiều bằng Argon2id kèm salt ngẫu nhiên.

    Không bao giờ ghi log hay đưa mật khẩu gốc vào thông điệp lỗi.
    """
    if not isinstance(plain_password, str) or not plain_password:
        raise ValueError("Mật khẩu không được để trống.")
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Kiểm tra mật khẩu gốc với chuỗi hash lưu trong cơ sở dữ liệu.

    Trả về False nếu mật khẩu sai hoặc chuỗi hash không hợp lệ,
    tuyệt đối không ghi log mật khẩu gốc.
    """
    if (
        not isinstance(plain_password, str)
        or not isinstance(password_hash, str)
        or not plain_password
        or not password_hash
    ):
        return False

    try:
        return bool(_password_hasher.verify(password_hash, plain_password))
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Kiểm tra xem chuỗi hash có cần băm lại khi nâng cấp tham số Argon2id hay không."""
    if not isinstance(password_hash, str) or not password_hash:
        return True
    try:
        return bool(_password_hasher.check_needs_rehash(password_hash))
    except InvalidHashError:
        return True


__all__ = [
    "hash_password",
    "needs_rehash",
    "verify_password",
]
