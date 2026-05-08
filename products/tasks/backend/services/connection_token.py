from __future__ import annotations

from dataclasses import dataclass
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
SANDBOX_EVENT_INGEST_AUDIENCE = "posthog:sandbox_event_ingest"
SANDBOX_EVENT_INGEST_TOKEN_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class SandboxEventIngestTokenPayload:
    run_id: str
    task_id: str
    team_id: int


def _normalize_pem_key(key: str) -> str:
    """Convert escaped newlines to actual newlines in PEM keys from env vars."""
    return key.replace("\\n", "\n")


@lru_cache(maxsize=1)
def get_sandbox_jwt_public_key() -> str:
    """
    Derive and cache the public key from the private key.
    """
    private_key_pem = settings.SANDBOX_JWT_PRIVATE_KEY
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
    private_key = settings.SANDBOX_JWT_PRIVATE_KEY
    if not private_key:
        raise ValueError("SANDBOX_JWT_PRIVATE_KEY setting is required for sandbox connection tokens")

    private_key = _normalize_pem_key(private_key)
    payload = {
        "run_id": str(task_run.id),
        "task_id": str(task_run.task_id),
        "team_id": task_run.team_id,
        "user_id": user_id,
        "distinct_id": distinct_id,
        "mode": task_run.mode,
        "exp": datetime.now(tz=UTC) + timedelta(hours=24),
        "aud": SANDBOX_CONNECTION_AUDIENCE,
    }

    return jwt.encode(payload, private_key, algorithm="RS256")


def create_sandbox_event_ingest_token(task_run: TaskRun, ttl: timedelta = SANDBOX_EVENT_INGEST_TOKEN_TTL) -> str:
    """
    Create a run-scoped JWT token for sandbox-to-Django live event ingest.

    This token intentionally carries no user identity and grants one capability:
    appending ordered live events for this task run.
    """
    private_key = settings.SANDBOX_JWT_PRIVATE_KEY
    if not private_key:
        raise ValueError("SANDBOX_JWT_PRIVATE_KEY setting is required for sandbox event ingest tokens")

    private_key = _normalize_pem_key(private_key)
    now = datetime.now(tz=UTC)
    payload = {
        "run_id": str(task_run.id),
        "task_id": str(task_run.task_id),
        "team_id": task_run.team_id,
        "iat": now,
        "exp": now + ttl,
        "aud": SANDBOX_EVENT_INGEST_AUDIENCE,
    }

    return jwt.encode(payload, private_key, algorithm="RS256")


def validate_sandbox_event_ingest_token(token: str) -> SandboxEventIngestTokenPayload:
    payload = jwt.decode(
        token,
        get_sandbox_jwt_public_key(),
        algorithms=["RS256"],
        audience=SANDBOX_EVENT_INGEST_AUDIENCE,
    )

    run_id = payload.get("run_id")
    task_id = payload.get("task_id")
    team_id = payload.get("team_id")

    if not isinstance(run_id, str) or not isinstance(task_id, str) or type(team_id) is not int:
        raise jwt.InvalidTokenError("Sandbox event ingest token has invalid claims")

    return SandboxEventIngestTokenPayload(run_id=run_id, task_id=task_id, team_id=team_id)
