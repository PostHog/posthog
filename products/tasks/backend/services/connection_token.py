from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

from django.conf import settings

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from products.tasks.backend.services.sandbox_config import SANDBOX_TTL_SECONDS

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


SANDBOX_CONNECTION_AUDIENCE = "posthog:sandbox_connection"
SANDBOX_EVENT_INGEST_AUDIENCE = "posthog:sandbox_event_ingest"
SANDBOX_EVENT_INGEST_TOKEN_TTL_BUFFER = timedelta(hours=1)
SANDBOX_EVENT_INGEST_TOKEN_TTL = timedelta(seconds=SANDBOX_TTL_SECONDS) + SANDBOX_EVENT_INGEST_TOKEN_TTL_BUFFER

SANDBOX_JWT_STATE_KID_KEY = "sandbox_jwt_kid"


@dataclass(frozen=True)
class SandboxEventIngestTokenPayload:
    run_id: str
    task_id: str
    team_id: int


@dataclass(frozen=True)
class _SandboxJwtKey:
    kid: str
    private_key_pem: str
    public_key_pem: str


def _normalize_pem_key(key: str) -> str:
    """Convert escaped newlines to actual newlines in PEM keys from env vars."""
    return key.replace("\\n", "\n")


def _derive_public_key_pem(private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None, backend=default_backend())
    return (
        private_key.public_key()
        .public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def _compute_kid(public_key_pem: str) -> str:
    """Stable short fingerprint of a public key, used as the JWT kid.

    The value is persisted on ``TaskRun.state`` at provision
    time and matched back when signing that run's tokens.
    """
    public_key = serialization.load_pem_public_key(public_key_pem.encode(), backend=default_backend())
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()[:16]


def _build_key(private_key_pem: str) -> _SandboxJwtKey:
    normalized = _normalize_pem_key(private_key_pem)
    public_key_pem = _derive_public_key_pem(normalized)
    return _SandboxJwtKey(kid=_compute_kid(public_key_pem), private_key_pem=normalized, public_key_pem=public_key_pem)


@lru_cache(maxsize=1)
def _key_registry() -> tuple[_SandboxJwtKey, dict[str, _SandboxJwtKey]]:
    """Return ``(primary_signing_key, {kid: key})`` for all configured sandbox JWT keys.

    The primary key (``SANDBOX_JWT_PRIVATE_KEY``) signs newly provisioned runs. The
    optional secondary key (``SANDBOX_JWT_PRIVATE_KEY_SECONDARY``) is additionally
    trusted for verification and signs runs whose sandbox was provisioned under it,
    this is what makes zero-downtime rotation of the primary key possible.
    """
    primary_pem = settings.SANDBOX_JWT_PRIVATE_KEY
    if not primary_pem:
        raise ValueError("SANDBOX_JWT_PRIVATE_KEY setting is required")

    primary = _build_key(primary_pem)
    registry: dict[str, _SandboxJwtKey] = {primary.kid: primary}

    secondary_pem = getattr(settings, "SANDBOX_JWT_PRIVATE_KEY_SECONDARY", None)
    if secondary_pem:
        secondary = _build_key(secondary_pem)
        registry.setdefault(secondary.kid, secondary)

    return primary, registry


def _primary_key() -> _SandboxJwtKey:
    return _key_registry()[0]


def get_primary_sandbox_jwt_kid() -> str:
    """``kid`` of the key newly provisioned sandboxes trust.

    Persist this on ``TaskRun.state`` at provision time so the run's tokens are later
    signed with the matching key even after the primary key is rotated.
    """
    return _primary_key().kid


def get_sandbox_jwt_public_key() -> str:
    """Public key (PEM) baked into newly provisioned sandboxes for verifying connection tokens."""
    return _primary_key().public_key_pem


def reset_sandbox_jwt_key_cache() -> None:
    """Clear the cached key registry. Used by tests after overriding the key settings."""
    _key_registry.cache_clear()


def _signing_key_for_run(task_run: TaskRun) -> _SandboxJwtKey:
    _, registry = _key_registry()
    kid = (task_run.state or {}).get(SANDBOX_JWT_STATE_KID_KEY)
    if kid and kid in registry:
        return registry[kid]
    return _primary_key()


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
    key = _signing_key_for_run(task_run)
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

    return jwt.encode(payload, key.private_key_pem, algorithm="RS256", headers={"kid": key.kid})


def create_sandbox_event_ingest_token(task_run: TaskRun, ttl: timedelta = SANDBOX_EVENT_INGEST_TOKEN_TTL) -> str:
    """
    Create a run-scoped JWT token for sandbox-to-Django live event ingest.

    This token intentionally carries no user identity and grants one capability:
    appending ordered live events for this task run.
    """
    now = datetime.now(tz=UTC)
    payload = {
        "run_id": str(task_run.id),
        "task_id": str(task_run.task_id),
        "team_id": task_run.team_id,
        "iat": now,
        "exp": now + ttl,
        "aud": SANDBOX_EVENT_INGEST_AUDIENCE,
    }

    return jwt.encode(payload, _primary_key().private_key_pem, algorithm="RS256")


def validate_sandbox_event_ingest_token(token: str) -> SandboxEventIngestTokenPayload:
    payload = jwt.decode(
        token,
        _primary_key().public_key_pem,
        algorithms=["RS256"],
        audience=SANDBOX_EVENT_INGEST_AUDIENCE,
    )

    run_id = payload.get("run_id")
    task_id = payload.get("task_id")
    team_id = payload.get("team_id")

    if not isinstance(run_id, str) or not isinstance(task_id, str) or type(team_id) is not int:
        raise jwt.InvalidTokenError("Sandbox event ingest token has invalid claims")

    return SandboxEventIngestTokenPayload(run_id=run_id, task_id=task_id, team_id=team_id)
