import hashlib
import hmac
import os
import secrets

# Current PBKDF2-SHA256 work factor (OWASP 2023 guidance).
# DESKAPP_PBKDF2_ITERATIONS lowers it for the test suite only; never set it in production.
PBKDF2_ITERATIONS = max(1000, int(os.environ.get("DESKAPP_PBKDF2_ITERATIONS", "600000")))
# Hashes written before the "pbkdf2_sha256$" format existed were plain hex at 100k iterations.
LEGACY_ITERATIONS = 100_000
_PREFIX = "pbkdf2_sha256"


def hash_password(password: str, salt: bytes = None, iterations: int = PBKDF2_ITERATIONS) -> tuple[str, str]:
    """
    Hashes a password using PBKDF2 with SHA256.
    Returns a tuple of (encoded_hash, salt_hex); encoded_hash is "pbkdf2_sha256$<iterations>$<hex>".
    """
    if salt is None:
        salt = os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
    return f"{_PREFIX}${iterations}${hash_bytes.hex()}", salt.hex()


def _parse(stored_hash: str) -> tuple[int, str]:
    if stored_hash.startswith(_PREFIX + "$"):
        _, iters, hex_digest = stored_hash.split("$", 2)
        return int(iters), hex_digest
    return LEGACY_ITERATIONS, stored_hash


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """Verifies a password against a stored hash and salt (constant-time compare)."""
    try:
        iterations, hex_digest = _parse(stored_hash)
        salt = bytes.fromhex(stored_salt)
        computed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations).hex()
        return hmac.compare_digest(computed, hex_digest)
    except Exception:
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the stored hash uses an older format or lower work factor."""
    try:
        iterations, _ = _parse(stored_hash)
        return iterations < PBKDF2_ITERATIONS
    except Exception:
        return True


def generate_password(length: int = 14) -> str:
    """Random password without ambiguous characters, for bootstrap/one-time credentials."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
