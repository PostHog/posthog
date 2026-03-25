from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache

from django.conf import settings

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

SANDBOX_CONNECTION_AUDIENCE = "posthog:sandbox_connection"


def _normalize_pem_key(key: str) -> str:
    return key.replace("\\n", "\n")


@lru_cache(maxsize=1)
def get_sandbox_jwt_public_key() -> str:
    private_key_pem = getattr(settings, "SANDBOX_JWT_PRIVATE_KEY", None)
    if not private_key_pem:
        raise ValueError("SANDBOX_JWT_PRIVATE_KEY setting is required")

    private_key_pem = _normalize_pem_key(private_key_pem)
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None, backend=default_backend())
    public_key = private_key.public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def create_sandbox_connection_token(team_id: int, user_id: int, distinct_id: str) -> str:
    private_key = getattr(settings, "SANDBOX_JWT_PRIVATE_KEY", None)
    if not private_key:
        raise ValueError("SANDBOX_JWT_PRIVATE_KEY setting is required for sandbox connection tokens")

    private_key = _normalize_pem_key(private_key)
    payload = {
        "team_id": team_id,
        "user_id": user_id,
        "distinct_id": distinct_id,
        "scope": "hogbot",
        "exp": datetime.now(tz=UTC) + timedelta(hours=24),
        "aud": SANDBOX_CONNECTION_AUDIENCE,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")
