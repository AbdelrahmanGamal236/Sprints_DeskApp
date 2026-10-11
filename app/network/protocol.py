"""Shared WebSocket protocol constants for the Central Server and workstation clients."""

# Bump when client and server can no longer talk to each other; all PCs must be upgraded together.
PROTOCOL_VERSION = 2

# Largest single WebSocket frame either side accepts. Exports are split into chunks well below this.
MAX_FRAME_BYTES = 4 * 1024 * 1024
EXPORT_CHUNK_BYTES = 512 * 1024

# Error codes carried in failed replies ({"ok": false, "code": ..., "error": ...})
ERR_AUTH_REQUIRED = "AUTH_REQUIRED"
ERR_SESSION_EXPIRED = "SESSION_EXPIRED"
ERR_PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
ERR_FORBIDDEN = "FORBIDDEN"
ERR_VALIDATION = "VALIDATION"
ERR_UNKNOWN_ACTION = "UNKNOWN_ACTION"
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_RATE_LIMITED = "RATE_LIMITED"
ERR_VERSION_MISMATCH = "VERSION_MISMATCH"
ERR_INTERNAL = "INTERNAL"

# Error codes that mean "the server will never accept this item" (offline queue marks it FAILED).
PERMANENT_ERROR_CODES = {ERR_FORBIDDEN, ERR_VALIDATION, ERR_UNKNOWN_ACTION, ERR_BAD_REQUEST}

# WebSocket close code used when the server revokes a live session (password reset, account change).
CLOSE_SESSION_REVOKED = 4001
