from cryptography.fernet import Fernet, InvalidToken
import pytest

from app.auth.encryption import decrypt_token, encrypt_token


def test_encrypt_decrypt_round_trip():
    plaintext = "test-oauth-access-token"

    ciphertext = encrypt_token(plaintext)

    assert ciphertext != plaintext
    assert decrypt_token(ciphertext) == plaintext


def test_tampered_ciphertext_fails_to_decrypt():
    plaintext = "test-oauth-access-token"
    ciphertext = encrypt_token(plaintext)

    # Change one character in the ciphertext.
    tampered = ciphertext[:-1] + (
        "A" if ciphertext[-1] != "A" else "B"
    )

    with pytest.raises(ValueError, match="Invalid or corrupted token ciphertext"):
        decrypt_token(tampered)