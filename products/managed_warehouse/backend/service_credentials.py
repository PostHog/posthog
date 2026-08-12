"""Mint short-lived, team-scoped duckgres service credentials from the control plane.

This is the PostHog-side half of the duckgres "Service Credentials" contract
(see duckgres/CLAUDE.md). A background job (dagster today) calls
``mint_service_credential`` once per run to get a credential bound to the
team's canonical ``posthog_team_<id>_rw`` project_user login — scoped to
exactly that team's warehouse schemas — instead of reading the org-wide root
credential out of a ``DuckgresServer`` row.

Contract essentials mirrored here (read the CP side for the authoritative
wording):

- ``POST /api/v1/orgs/{org}/teams/{team}/service-credentials``, authed with
  the existing internal secret — the same trust class as every other
  provisioning call.
- Expiry is enforced by ROTATION on the CP, not by the caller honoring
  ``expires_at``: a still-valid grant is returned WITHOUT a password (the
  caller already holds it from a prior fetch — or must ask for a rotation).
- ``force_rotate=True`` is how a caller with nothing cached gets a password.
  First call of a run must pass it.
- Established connections are never killed on expiry (handshake-only
  semantics, RDS-IAM style); only NEW connections need a live credential.
- Every successful mint carries a ``connect`` block (host, port, database,
  sslmode) — the dial target for the credential. Service-credential
  connections are built ENTIRELY from it, never from the stored
  ``DuckgresServer`` row; a mint response without it is an older CP than the
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
    through this: a malformed mint response can still carry a live
    ``password`` (e.g. present-but-empty username alongside a password), and
    the caller's broad fallback logs whatever lands in the exception text.
    A redacted placeholder keeps the debugging value of seeing the payload's
    shape without leaking the grant.
    """
    if isinstance(data, dict):
        return {
            key: ("<redacted>" if "password" in str(key).lower() else _redact_payload(value))
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
    force_rotate: bool = False,
) -> ServiceCredential:
    """Mint-or-reuse the team's project_user credential for a short-lived job.

    Returns a ``ServiceCredential``. Raises ``ServiceCredentialUnavailable``
    on any CP-side failure — the CP's own error string is propagated verbatim
    so operators see the real reason (unknown org, disabled team, DB down).
    """
    # Imported here to avoid an import cycle: presentation.views imports the
    # facade, the facade (via client.py → service-credential-aware conninfo)
    # imports this module.
    from products.managed_warehouse.backend.presentation.views import _request  # noqa: PLC0415

    ttl_seconds = max(MIN_CREDENTIAL_TTL_SECONDS, min(ttl_seconds, MAX_CREDENTIAL_TTL_SECONDS))

    response = _request(
        "POST",
        organization_id,
        f"/teams/{team_id}/service-credentials",
        json_body={
            "team_id": team_id,
            "principal": principal,
            "ttl_seconds": ttl_seconds,
            "force_rotate": force_rotate,
        },
        # Backend caller: never gate on the user-facing data-warehouse feature
        # flag (a dagster worker may not have the flag definition loaded).
        require_enabled=False,
    )
    if not status.is_success(response.status_code):
        raise ServiceCredentialUnavailable(
            f"service credential mint failed for org={organization_id} team={team_id}: "
            f"HTTP {response.status_code}: {_redact_payload(response.data)!r}"
        )
    data: dict[str, Any] = response.data if isinstance(response.data, dict) else {}
    username = data.get("username")
    if not username:
        # Never stringify the CP payload verbatim: a malformed response can
        # still carry a real `password`, and the backfill's broad fallback
        # handler logs whatever exception text we raise here.
        raise ServiceCredentialUnavailable(f"mint returned no username: {_redact_payload(data)!r}")
    expires_raw = data.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ServiceCredentialUnavailable(f"mint returned unparseable expires_at {expires_raw!r}") from exc
    connect = _parse_connect(data)
    credential = ServiceCredential(
        username=str(username),
        password=str(data.get("password") or ""),
        expires_at=expires_at,
        rotated=bool(data.get("password")),
        connect=connect,
    )
    logger.info(
        "duckgres_service_credential_minted",
        organization_id=organization_id,
        team_id=team_id,
        principal=principal,
        rotated=credential.rotated,
        expires_at=expires_at.isoformat(),
        connect_host=connect.host,
        connect_port=connect.port,
    )
    return credential


def _parse_connect(data: dict[str, Any]) -> ServiceCredentialConnect:
    """Parse the mandatory ``connect`` block from a successful mint response.

    STRICT: every successful mint must carry ``connect`` with all four fields
    (host, port, database, sslmode) — the CP contract since the connect-bundle
    change. A 2xx without it means the CP is older than the contract; the
    service-credential conninfo builder no longer reads the ``DuckgresServer``
    row, so there is nothing to fall back to here and we raise
    ``ServiceCredentialUnavailable`` (the caller's broad fallback to root
    engages — the established transitional degradation).
    """
    raw = data.get("connect")
    if not isinstance(raw, dict):
        # Redact, as everywhere else in this module: the malformed payload can
        # still carry a live `password`, and the caller logs exception text.
        raise ServiceCredentialUnavailable(f"mint returned no connect block: {_redact_payload(data)!r}")
    host = raw.get("host")
    database = raw.get("database")
    sslmode = raw.get("sslmode")
    port_raw: Any = raw.get("port")
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 0
    if not host or not database or not sslmode or port <= 0:
        raise ServiceCredentialUnavailable(f"mint returned incomplete connect block: {_redact_payload(data)!r}")
    return ServiceCredentialConnect(host=str(host), port=port, database=str(database), sslmode=str(sslmode))
