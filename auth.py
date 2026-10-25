import hashlib
import hmac
import re
import secrets

import db

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{3,32}")
MIN_PASSWORD_LENGTH = 8
SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1}


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, **SCRYPT_PARAMS)


def register(username: str, password: str) -> dict:
    """Create an account and return {"id", "username"}. Raises ValueError with a user-facing message."""
    username = username.strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Username must be 3-32 characters: letters, numbers, '.', '_' or '-'.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    salt = secrets.token_bytes(16)
    user_id = db.create_user(username, f"scrypt${salt.hex()}${_scrypt(password, salt).hex()}")
    if user_id is None:
        raise ValueError("That username is already taken.")
    return {"id": user_id, "username": username}


def login(username: str, password: str) -> dict | None:
    """Return {"id", "username"} if the credentials are valid, else None."""
    user = db.get_user(username.strip())
    if not user:
        return None
    _, salt_hex, hash_hex = user["password_hash"].split("$")
    if not hmac.compare_digest(_scrypt(password, bytes.fromhex(salt_hex)), bytes.fromhex(hash_hex)):
        return None
    return {"id": user["id"], "username": user["username"]}
