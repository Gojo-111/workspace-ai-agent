from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings


def _get_fernet() -> Fernet:
    """Create the Fernet cipher using the configured token encryption key."""
    return Fernet(settings.TOKEN_ENCRYPTION_KEY)


def encrypt_token(plaintext: str) -> str:
    """Encrypt a plaintext OAuth token and return the ciphertext."""
    if not plaintext:
        raise ValueError("Token plaintext cannot be empty")

    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    """Decrypt an OAuth token ciphertext and return the plaintext."""
    if not ciphertext:
        raise ValueError("Token ciphertext cannot be empty")

    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Invalid or corrupted token ciphertext") from exc