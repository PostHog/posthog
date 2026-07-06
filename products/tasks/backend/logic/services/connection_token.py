from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from django.conf import settings

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from products.tasks.backend.logic.services.sandbox_config import SANDBOX_TTL_SECONDS

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


SANDBOX_CONNECTION_AUDIENCE = "posthog:sandbox_connection"
SANDBOX_EVENT_INGEST_AUDIENCE = "posthog:sandbox_event_ingest"
SANDBOX_EVENT_INGEST_TOKEN_TTL_BUFFER = timedelta(hours=1)
SANDBOX_EVENT_INGEST_TOKEN_TTL = timedelta(seconds=SANDBOX_TTL_SECONDS) + SANDBOX_EVENT_INGEST_TOKEN_TTL_BUFFER

SANDBOX_JWT_STATE_KID_KEY = "sandbox_jwt_kid"

STREAM_READ_AUDIENCE = "posthog:stream_read"
# Short-lived on purpose: the agent-proxy validates these tokens statelessly, so the TTL bounds
# how long a user who lost project access can keep reconnecting to a stream. The client fetches a
# fresh token from the stream_token endpoint (which re-checks access) on every connect, and again
# when a reconnect is rejected with a 401 after the token expires mid-stream.
STREAM_READ_TOKEN_TTL = timedelta(minutes=15)


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


@dataclass(frozen=True)
class StreamReadTokenPayload:
    run_id: str
    task_id: str
    team_id: int


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
    """Public key (PEM) used to verify sandbox tokens, baked into newly provisioned sandboxes.

    Prefers an explicitly configured public key so a verify-only service (the agent-proxy)
    never needs the private key. Falls back to the primary signing key's public half for
    Django, which mints tokens.
    """
    public_key_pem = settings.SANDBOX_JWT_PUBLIC_KEY
    if public_key_pem:
        return _normalize_pem_key(public_key_pem)
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


def _verification_public_keys() -> list[str]:
    """Public-key PEMs to verify sandbox tokens against.

    Prefers explicitly configured public keys so a verify-only context (the agent-proxy, or a
    public-key-only Django process) never needs the private key; the optional secondary public key
    is additionally trusted during a rotation overlap. Falls back to the signing registry's public
    halves when no explicit public key is configured (Django, which mints tokens).
    """
    explicit = settings.SANDBOX_JWT_PUBLIC_KEY
    if explicit:
        pems = [_normalize_pem_key(explicit)]
        secondary = settings.SANDBOX_JWT_PUBLIC_KEY_SECONDARY
        if secondary:
            pems.append(_normalize_pem_key(secondary))
        return pems
    _, registry = _key_registry()
    return [key.public_key_pem for key in registry.values()]


def _decode_sandbox_token(token: str, audience: str) -> dict[str, Any]:
    """Verify a sandbox JWT against every trusted public key, returning the first that validates.

    Trusting both the primary and the rotation-secondary key is what lets the agent-proxy token
    legs survive a primary-key rotation without downtime: a token signed under either key still
    verifies. Only a signature mismatch advances to the next key; expiry and audience errors are
    key-independent and propagate immediately.
    """
    last_error: jwt.InvalidTokenError | None = None
    for public_key_pem in _verification_public_keys():
        try:
            return jwt.decode(token, public_key_pem, algorithms=["RS256"], audience=audience)
        except jwt.InvalidSignatureError as exc:
            last_error = exc
    raise last_error or jwt.InvalidTokenError("No sandbox JWT keys configured")


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


def _encode_run_scoped_token(task_run: TaskRun, audience: str, ttl: timedelta) -> str:
    """Encode a run-scoped JWT carrying no user identity, signed with the run's key.

    Shared by the event-ingest and stream-read tokens; they stay distinct capabilities
    (write vs read) kept apart by ``audience`` rather than by the encoding. Signing with
    the run's provisioned key (via ``kid``) keeps both legs working across key rotation.
    """
    now = datetime.now(tz=UTC)
    payload = {
        "run_id": str(task_run.id),
        "task_id": str(task_run.task_id),
        "team_id": task_run.team_id,
        "iat": now,
        "exp": now + ttl,
        "aud": audience,
    }
    key = _signing_key_for_run(task_run)
    return jwt.encode(payload, key.private_key_pem, algorithm="RS256", headers={"kid": key.kid})


def create_sandbox_event_ingest_token(task_run: TaskRun, ttl: timedelta = SANDBOX_EVENT_INGEST_TOKEN_TTL) -> str:
    """
    Create a run-scoped JWT token for sandbox-to-Django live event ingest.

    This token intentionally carries no user identity and grants one capability:
    appending ordered live events for this task run.
    """
    return _encode_run_scoped_token(task_run, SANDBOX_EVENT_INGEST_AUDIENCE, ttl)


def validate_sandbox_event_ingest_token(token: str) -> SandboxEventIngestTokenPayload:
    payload = _decode_sandbox_token(token, SANDBOX_EVENT_INGEST_AUDIENCE)

    run_id = payload.get("run_id")
    task_id = payload.get("task_id")
    team_id = payload.get("team_id")

    if not isinstance(run_id, str) or not isinstance(task_id, str) or type(team_id) is not int:
        raise jwt.InvalidTokenError("Sandbox event ingest token has invalid claims")

    return SandboxEventIngestTokenPayload(run_id=run_id, task_id=task_id, team_id=team_id)


def create_stream_read_token(task_run: TaskRun, ttl: timedelta = STREAM_READ_TOKEN_TTL) -> str:
    """
    Create a run-scoped JWT that authorizes reading a task run's live event stream.

    Minted by Django (which authorizes the requesting user first) for the browser to
    present to the standalone agent-proxy, which verifies it statelessly with the
    public key. Carries no user identity and grants one capability: reading this
    task run's stream.
    """
    return _encode_run_scoped_token(task_run, STREAM_READ_AUDIENCE, ttl)


def validate_stream_read_token(token: str) -> StreamReadTokenPayload:
    payload = _decode_sandbox_token(token, STREAM_READ_AUDIENCE)

    run_id = payload.get("run_id")
    task_id = payload.get("task_id")
    team_id = payload.get("team_id")

    if not isinstance(run_id, str) or not isinstance(task_id, str) or type(team_id) is not int:
        raise jwt.InvalidTokenError("Stream read token has invalid claims")

    return StreamReadTokenPayload(run_id=run_id, task_id=task_id, team_id=team_id)
