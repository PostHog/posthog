from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

from django.conf import settings

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


SANDBOX_CONNECTION_AUDIENCE = "posthog:sandbox_connection"


def _normalize_pem_key(key: str) -> str:
    """Convert escaped newlines to actual newlines in PEM keys from env vars."""
    return key.replace("\\n", "\n")


@lru_cache(maxsize=1)
def get_sandbox_jwt_public_key() -> str:
    """
    Derive and cache the public key from the private key.
    """
    private_key_pem = getattr(settings, "SANDBOX_JWT_PRIVATE_KEY", None)
    if not private_key_pem:
        raise ValueError("SANDBOX_JWT_PRIVATE_KEY setting is required")

    private_key_pem = _normalize_pem_key(private_key_pem)
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None, backend=default_backend())
    public_key = private_key.public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def create_sandbox_connection_token(task_run: TaskRun, user_id: int, distinct_id: str) -> str:
    """
    Create a JWT connection token for direct sandbox connections.

    Uses RS256 asymmetric signing so the sandbox can verify tokens with a public key
    but cannot forge new tokens (only Django has the private key).

    Args:
        task_run: The TaskRun to create a token for
        user_id: The user ID making the connection
        distinct_id: The user's distinct_id for analytics

    Returns:
        A signed JWT token valid for 24 hours
    """
    private_key = getattr(settings, "SANDBOX_JWT_PRIVATE_KEY", None)
    if not private_key:
        raise ValueError("SANDBOX_JWT_PRIVATE_KEY setting is required for sandbox connection tokens")

    private_key = _normalize_pem_key(private_key)
    payload = {
        "run_id": str(task_run.id),
        "task_id": str(task_run.task_id),
        "team_id": task_run.team_id,
        "user_id": user_id,
        "distinct_id": distinct_id,
        "exp": datetime.now(tz=UTC) + timedelta(hours=24),
        "aud": SANDBOX_CONNECTION_AUDIENCE,
    }

    return jwt.encode(payload, private_key, algorithm="RS256")
