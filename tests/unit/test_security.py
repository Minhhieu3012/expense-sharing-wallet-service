import logging

import pytest

from app.core.security import hash_password, needs_rehash, verify_password


def test_hash_password_returns_argon2id_hash_and_never_plaintext() -> None:
    # Arrange
    plain = "StrongPassword@123"

    # Act
    hashed = hash_password(plain)

    # Assert
    assert hashed.startswith("$argon2id$")
    assert hashed != plain
    assert plain not in hashed
    assert len(hashed) <= 255  # khớp giới hạn VARCHAR(255) của cột users.password_hash


def test_hash_password_generates_unique_random_salt_each_time() -> None:
    # Arrange
    plain = "SamePassword@2026"

    # Act
    hash_1 = hash_password(plain)
    hash_2 = hash_password(plain)

    # Assert: cùng mật khẩu nhưng phải sinh ra 2 chuỗi hash khác nhau nhờ salt ngẫu nhiên
    assert hash_1 != hash_2
    assert verify_password(plain, hash_1) is True
    assert verify_password(plain, hash_2) is True


def test_verify_password_succeeds_for_matching_unicode_and_long_passwords() -> None:
    # Arrange: kiểm tra tiếng Việt có dấu và mật khẩu > 72 bytes (không bị cắt ngắn như bcrypt)
    unicode_password = "MậtKhẩuSiêuMạnh@ĐàLạt2026!"
    long_password = "A" * 120 + "unique-tail-1"
    other_long_password = "A" * 120 + "unique-tail-2"

    # Act
    unicode_hash = hash_password(unicode_password)
    long_hash = hash_password(long_password)

    # Assert
    assert verify_password(unicode_password, unicode_hash) is True
    assert verify_password(long_password, long_hash) is True
    assert verify_password(other_long_password, long_hash) is False


def test_verify_password_returns_false_for_wrong_or_malformed_inputs() -> None:
    # Arrange
    hashed = hash_password("CorrectPassword@123")

    # Act & Assert
    assert verify_password("WrongPassword@123", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password("CorrectPassword@123", "") is False
    assert verify_password("CorrectPassword@123", "not-a-valid-argon2-hash") is False
    assert verify_password("CorrectPassword@123", "CorrectPassword@123") is False


def test_hash_password_rejects_empty_password() -> None:
    with pytest.raises(ValueError, match="Mật khẩu không được để trống"):
        hash_password("")


def test_needs_rehash_false_for_fresh_hash_and_true_for_invalid_hash() -> None:
    # Arrange
    fresh_hash = hash_password("FreshPassword@123")

    # Assert
    assert needs_rehash(fresh_hash) is False
    assert needs_rehash("corrupted-hash") is True
    assert needs_rehash("") is True


def test_password_never_appears_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange
    secret_password = "UltraSecretPassword_DO_NOT_LOG_999"

    # Act
    with caplog.at_level(logging.DEBUG):
        hashed = hash_password(secret_password)
        assert verify_password(secret_password, hashed) is True
        assert verify_password(secret_password, "invalid-hash") is False

    # Assert
    assert secret_password not in caplog.text
