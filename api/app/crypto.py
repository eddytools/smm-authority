"""Encryption for stored OAuth tokens (Fernet: AES-128-CBC + HMAC). Keys come from SMM_TOKEN_ENCRYPTION_KEY, a
comma-separated list so a key can be rotated: the first encrypts, every key can decrypt.

Generate one with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class TokenCipherError(Exception):
    pass


class TokenCipher:
    def __init__(self, keys: str):
        try:
            self._fernet = MultiFernet([Fernet(k.strip().encode()) for k in keys.split(",") if k.strip()])
        except (ValueError, TypeError):
            raise TokenCipherError("SMM_TOKEN_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64-encoded bytes)")

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            raise TokenCipherError("Stored token could not be decrypted (was the encryption key changed?)")
