"""Mint short-lived, org-scoped duckgres service credentials from the control plane.

This is the PostHog-side half of the duckgres "Service Credentials" contract
(see duckgres/CLAUDE.md). A background job (dagster today) calls
``mint_service_credential`` once per run to get a credential scoped to the
org's warehouse access — minted as its own server-side grant ROW (not a
rewrite of a shared team login's hash) instead of reading the stored login
out of a ``DuckgresServer`` row.

Contract essentials mirrored here (read the CP side for the authoritative
wording):

- ``POST /api/v1/orgs/{org}/service-credentials``, authed with the existing
  internal secret — the same trust class as every other provisioning call.
  The response's ``credential_id`` is CP-generated (``svc_<24 random hex>``).
- Every mint creates a new grant and returns its new ``credential_id`` and
  ``credential_secret``. ``principal`` is audit metadata, so concurrent jobs
  can use the same principal without sharing or rotating each other's grants.
- ``POST /api/v1/orgs/{org}/service-credentials/refresh`` (via
  ``refresh_service_credential``) rotates the secret for one known
  ``credential_id``. Callers retain that ID to manage the grant they minted.
- The credential is live ONLY until ``expires_at``; refresh before lapse.
  Established connections are never killed on expiry (handshake-only
  semantics, RDS-IAM style); only NEW connections need a live credential.
- Every successful mint/refresh carries a ``connect`` block (host, port,
  database, sslmode) — the dial target for the credential. Service-credential
  connections are built ENTIRELY from it, never from the stored
  ``DuckgresServer`` row; a response without it is an older CP than the
  contract and is rejected as unavailable.

Keep this module's request/response shapes byte-compatible with
``controlplane/provisioning/service_credential.go``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from rest_framework import status

from products.managed_warehouse.backend.facade.contracts import (
    ServiceCredential,
    ServiceCredentialConnect,
    ServiceCredentialUnavailable,
)

__all__ = [
    "DEFAULT_CREDENTIAL_TTL_SECONDS",
    "MAX_CREDENTIAL_TTL_SECONDS",
    "MIN_CREDENTIAL_TTL_SECONDS",
    "ServiceCredential",
    "ServiceCredentialConnect",
    "ServiceCredentialUnavailable",
    "mint_service_credential",
    "refresh_service_credential",
]

logger = structlog.get_logger(__name__)

# Mirrored from controlplane/provisioning/service_credential.go. Keep these
# three constants in sync with the CP's clamping policy.
MIN_CREDENTIAL_TTL_SECONDS = 60
MAX_CREDENTIAL_TTL_SECONDS = 3600
DEFAULT_CREDENTIAL_TTL_SECONDS = 900  # 15 min — the RDS-IAM precedent


def _redact_payload(data: Any) -> Any:
    """Shape-preserving copy with credential-bearing values removed.

    Every error path in this module that mentions the CP response must go
    through this: a malformed mint response can still carry a live secret
    (e.g. a present-but-empty credential_id alongside a credential_secret),
    and the caller's broad fallback logs whatever lands in the exception
    text. A redacted placeholder keeps the debugging value of seeing the
    payload's shape without leaking the grant.
    """
    if isinstance(data, dict):
        return {
            key: (
                "<redacted>"
                if any(marker in str(key).lower() for marker in ("password", "secret"))
                else _redact_payload(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_redact_payload(item) for item in data]
    return data


def mint_service_credential(
    organization_id: str,
    team_id: int,
    *,
    principal: str,
    ttl_seconds: int = DEFAULT_CREDENTIAL_TTL_SECONDS,
    timeout_seconds: int | None = None,
) -> ServiceCredential:
    """Mint a new org-scoped service credential for a short-lived job.

    Returns a ``ServiceCredential``. Raises ``ServiceCredentialUnavailable``
    on any CP-side failure — the CP's own error string is propagated verbatim
    so operators see the real reason (unknown org, DB down).

    ``team_id`` is kept as a parameter purely for backwards compatibility
    with callers that still have it in scope. It is NOT sent on the wire:
    under the org-scoped per-credential-grant contract the control plane does
    not key credentials by team. ``principal`` is audit metadata and does not
    identify or reuse a grant.
    """
    # Imported here to avoid an import cycle: presentation.views imports the
    # facade, the facade (via client.py → service-credential-aware conninfo)
    # imports this module.
    from products.managed_warehouse.backend.presentation.views import _request  # noqa: PLC0415

    ttl_seconds = max(MIN_CREDENTIAL_TTL_SECONDS, min(ttl_seconds, MAX_CREDENTIAL_TTL_SECONDS))

    request_kwargs: dict[str, Any] = {
        "json_body": {
            "principal": principal,
            "ttl_seconds": ttl_seconds,
        },
        "require_enabled": False,
    }
    if timeout_seconds is not None:
        request_kwargs["timeout"] = timeout_seconds

    response = _request(
        "POST",
        organization_id,
        "/service-credentials",
        # Backend caller: never gate on the user-facing data-warehouse feature
        # flag (a dagster worker may not have the flag definition loaded).
        **request_kwargs,
    )
    if not status.is_success(response.status_code):
        raise ServiceCredentialUnavailable(
            f"service credential mint failed for org={organization_id}: "
            f"HTTP {response.status_code}: {_redact_payload(response.data)!r}"
        )
    data: dict[str, Any] = response.data if isinstance(response.data, dict) else {}
    credential = _parse_credential_response(data, action="mint")
    logger.info(
        "duckgres_service_credential_minted",
        organization_id=organization_id,
        team_id=team_id,
        principal=principal,
        credential_id=credential.credential_id,
        expires_at=credential.expires_at.isoformat(),
        connect_host=credential.connect.host,
        connect_port=credential.connect.port,
    )
    return credential


def refresh_service_credential(
    organization_id: str,
    credential_id: str,
    *,
    ttl_seconds: int = DEFAULT_CREDENTIAL_TTL_SECONDS,
) -> ServiceCredential:
    """Rotate the secret on a known credential before it lapses.

    Refresh always returns a fresh ``credential_secret`` for the supplied
    ``credential_id``. Addressing the grant by ID prevents one caller from
    refreshing another caller's credential.

    Returns a ``ServiceCredential``. Raises ``ServiceCredentialUnavailable``
    on any CP-side failure (unknown credential_id, lapsed credential, 5xx).
    The CP's own error string is propagated verbatim so operators see the
    real reason.
    """
    # See mint_service_credential for the import-cycle note.
    from products.managed_warehouse.backend.presentation.views import _request  # noqa: PLC0415

    ttl_seconds = max(MIN_CREDENTIAL_TTL_SECONDS, min(ttl_seconds, MAX_CREDENTIAL_TTL_SECONDS))

    response = _request(
        "POST",
        organization_id,
        "/service-credentials/refresh",
        json_body={
            "credential_id": credential_id,
            "ttl_seconds": ttl_seconds,
        },
        require_enabled=False,
    )
    if not status.is_success(response.status_code):
        raise ServiceCredentialUnavailable(
            f"service credential refresh failed for org={organization_id} credential_id={credential_id}: "
            f"HTTP {response.status_code}: {_redact_payload(response.data)!r}"
        )
    data: dict[str, Any] = response.data if isinstance(response.data, dict) else {}
    credential = _parse_credential_response(data, action="refresh")
    logger.info(
        "duckgres_service_credential_refreshed",
        organization_id=organization_id,
        credential_id=credential.credential_id,
        expires_at=credential.expires_at.isoformat(),
        connect_host=credential.connect.host,
        connect_port=credential.connect.port,
    )
    return credential


def _parse_credential_response(data: dict[str, Any], *, action: str) -> ServiceCredential:
    """Parse a successful mint/refresh response into a ``ServiceCredential``.

    Shared by both endpoints: the response contract is the same shape
    (``credential_id``, ``credential_secret``, ``expires_at``, ``connect``).
    Mint and refresh both require a plaintext secret in their response.
    """
    credential_id = data.get("credential_id")
    if not credential_id:
        # Never stringify the CP payload verbatim: a malformed response can
        # still carry a live `credential_secret`, and the backfill's broad
        # fallback handler logs whatever exception text we raise here.
        raise ServiceCredentialUnavailable(f"{action} returned no credential_id: {_redact_payload(data)!r}")
    credential_secret = data.get("credential_secret")
    if not credential_secret:
        raise ServiceCredentialUnavailable(f"{action} returned no credential_secret: {_redact_payload(data)!r}")
    expires_raw = data.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ServiceCredentialUnavailable(f"{action} returned unparseable expires_at {expires_raw!r}") from exc
    connect = _parse_connect(data, action=action)
    return ServiceCredential(
        credential_id=str(credential_id),
        credential_secret=str(credential_secret),
        expires_at=expires_at,
        connect=connect,
    )


def _parse_connect(data: dict[str, Any], *, action: str = "mint") -> ServiceCredentialConnect:
    """Parse the mandatory ``connect`` block from a successful response.

    STRICT: every successful mint/refresh must carry ``connect`` with all
    four fields (host, port, database, sslmode) — the CP contract since the
    connect-bundle change. A 2xx without it means the CP is older than the
    contract; the service-credential conninfo builder no longer reads the
    ``DuckgresServer`` row, so there is nothing to fall back to here and we
    raise ``ServiceCredentialUnavailable`` so the caller can apply its configured fallback.
    """
    raw = data.get("connect")
    if not isinstance(raw, dict):
        # Redact, as everywhere else in this module: the malformed payload can
        # still carry a live `credential_secret`, and the caller logs
        # exception text.
        raise ServiceCredentialUnavailable(f"{action} returned no connect block: {_redact_payload(data)!r}")
    host = raw.get("host")
    database = raw.get("database")
    sslmode = raw.get("sslmode")
    port_raw: Any = raw.get("port")
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 0
    if not host or not database or not sslmode or port <= 0:
        raise ServiceCredentialUnavailable(f"{action} returned incomplete connect block: {_redact_payload(data)!r}")
    return ServiceCredentialConnect(host=str(host), port=port, database=str(database), sslmode=str(sslmode))
