import hashlib
import os

def hash_password(password: str, salt: bytes = None) -> tuple[str, str]:
    """
    Hashes a password using PBKDF2 with SHA256.
    Returns a tuple of (hash_hex, salt_hex).
    """
    if salt is None:
        salt = os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return hash_bytes.hex(), salt.hex()

def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """
    Verifies a password against a stored hash and salt.
    """
    try:
        salt = bytes.fromhex(stored_salt)
        computed_hash, _ = hash_password(password, salt)
        return computed_hash == stored_hash
    except Exception:
        return False
