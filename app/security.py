from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

from app.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(account_id: UUID, role: str) -> str:
    settings = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode(
        {"sub": str(account_id), "role": role, "exp": expires},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def decode_access_token(token: str) -> dict[str, str]:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        options={"require": ["sub", "exp", "role"]},
    )


def _fernet() -> Fernet:
    key = get_settings().payment_token_encryption_key
    if not key:
        raise RuntimeError(
            "PAYMENT_TOKEN_ENCRYPTION_KEY is required to store saved card references"
        )
    try:
        return Fernet(key.get_secret_value().encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("PAYMENT_TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from exc


def encrypt_provider_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_provider_token(encrypted_token: str) -> str:
    try:
        return _fernet().decrypt(encrypted_token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Saved payment reference cannot be decrypted") from exc


def token_fingerprint(token: str) -> str:
    return sha256(token.encode()).hexdigest()
