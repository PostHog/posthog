"""Read the managed-warehouse target an organization's warehouse is reachable at.

The warehouse-source host guard needs one fact: may this organization dial its own managed
warehouse, and at which address. The control plane owns that answer. This module is the only
place that asks, so the guard stays free of transport details and the read has one cache.

Hogtower answers it through `GET /warehouses/{org}`. Its `connection` block is present only
while the warehouse is `ready`, and its `host` is `<warehouse_name>.dw.<env>.postwh.com` with
port 5432. A warehouse that is provisioning, deleting, failed or absent yields no target, so a
caller that gets None must treat the organization as having no reachable managed warehouse.

Failures are not cached as successes and never raise past this module. They return None, which
denies the exemption: refusing a managed source is the safe direction, and the guard has no
useful reply for a control-plane outage.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.cache import cache

import requests as http_requests
import structlog

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTarget  # noqa: F401
from products.managed_warehouse.backend.presentation import hogtower

logger = structlog.get_logger(__name__)

# The ports the shared `dw` load balancer publishes, keyed by the source type that legitimately
# reaches it. Postgres-wire sources speak the 5432 listener. The Trino source speaks the gateway
# on 443. Arrow Flight on 8815 has no warehouse source, so nothing is exempt there.
MANAGED_WAREHOUSE_PORTS_BY_SOURCE_TYPE: dict[str, frozenset[int]] = {
    "postgres": frozenset({5432}),
    "trino": frozenset({443}),
}

# The dataclasses name the ports directly so a caller that already knows its source type does not
# import the mapping above.
MANAGED_WAREHOUSE_SOURCE_TYPES = frozenset(MANAGED_WAREHOUSE_PORTS_BY_SOURCE_TYPE)


# The DNS zone each deployment serves managed warehouses under. It lives here rather than in
# `presentation.views` because the warehouse-source host guard reads it, and importing a DRF
# module from a Temporal worker's connect path is how a presentation dependency ends up in a
# background process. `views.managed_warehouse_domain` keeps its own copy because presentation
# cannot import a plain backend module without breaking the facade contract, and both assert the
# same values in tests.
_MANAGED_WAREHOUSE_DOMAINS = {
    "US": "us.postwh.com",
    "EU": "eu.postwh.com",
    "DEV": "dev.postwh.com",
}


def managed_warehouse_domain() -> str:
    """The zone managed warehouse hostnames are served under in this deployment."""
    from django.conf import settings  # noqa: PLC0415

    deployment = (getattr(settings, "CLOUD_DEPLOYMENT", None) or "").upper()
    return _MANAGED_WAREHOUSE_DOMAINS.get(deployment, "test.local")


def _ingress_ips() -> tuple[str, ...]:
    """The configured ingress address set, read per call so a settings override takes effect."""
    from django.conf import settings  # noqa: PLC0415

    configured = getattr(settings, "MANAGED_WAREHOUSE_INGRESS_IPS", "") or ""
    return tuple(ip.strip() for ip in configured.split(",") if ip.strip())


# A ready warehouse's host changes only when an operator renames it, so a positive answer is worth
# caching. Every other answer is short-lived: a warehouse that just became ready must not stay
# denied for the whole positive TTL.
_TARGET_CACHE_TTL_SECONDS = 300
_DENIAL_CACHE_TTL_SECONDS = 30
_CONTROL_PLANE_TIMEOUT_SECONDS = 2


# The canonical definition is the contract, because the product's public interface exposes the
# facade and not this module. The caching and the control-plane read live here; the type does not.


def _normalize_host(host: str) -> str:
    """Lowercase a hostname and drop one root-zone trailing dot, as the guard does."""
    return host.lower().strip().rstrip(".")


def _canonical_ip(value: str) -> str:
    """Compare addresses as numbers, so an IPv4-mapped IPv6 form matches its IPv4 spelling."""
    import ipaddress  # noqa: PLC0415

    try:
        parsed = ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return value
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return str(parsed)


def _cache_key(organization_id: str, source_type: str) -> str:
    return f"managed_warehouse_target:{organization_id}:{source_type}"


def get_managed_warehouse_target(organization_id: str | UUID, *, source_type: str) -> ManagedWarehouseTarget | None:
    """The managed warehouse `organization_id` may reach from a `source_type` source, or None.

    Returns None for a source type the managed warehouse does not serve, for an organization
    without a ready warehouse, and when the control plane cannot answer.
    """
    ports = MANAGED_WAREHOUSE_PORTS_BY_SOURCE_TYPE.get(source_type)
    if ports is None:
        return None

    org_id = str(organization_id)
    key = _cache_key(org_id, source_type)
    cached = _cache_get(key)
    if isinstance(cached, ManagedWarehouseTarget):
        return cached
    if cached == _NO_TARGET:
        return None

    host = _read_ready_host(org_id)
    if host is None:
        _cache_denial(key)
        return None

    target = ManagedWarehouseTarget(host=host, ports=ports)
    _cache_target(key, target)
    return target


# A sentinel is cached rather than None: Django's cache stores None as a miss, so a denial would
# otherwise be re-read from the control plane on every dial. It is a string, not `object()`,
# because the cache pickles its values and an unpickled sentinel is a new object. A denial
# compared by identity would therefore never hit, and every denied dial during an outage would
# pay the full control-plane timeout.
_NO_TARGET = "no-managed-warehouse-target"


def _cache_get(key: str) -> object:
    """The cached answer for `key`, or None when absent.

    A cache fault denies rather than raising: the guard runs inside a connect, and an exception
    here would replace a clear refusal with an opaque connection error.
    """
    try:
        return cache.get(key)
    except Exception:
        logger.exception("managed_warehouse_target_cache_read_failed")
        return None


def _cache_denial(key: str) -> None:
    try:
        cache.set(key, _NO_TARGET, _DENIAL_CACHE_TTL_SECONDS)
    except Exception:
        logger.exception("managed_warehouse_target_denial_cache_failed")


def _cache_target(key: str, target: ManagedWarehouseTarget) -> None:
    try:
        cache.set(key, target, _TARGET_CACHE_TTL_SECONDS)
    except Exception:
        # A positive answer that cannot be cached still answers this dial.
        logger.exception("managed_warehouse_target_cache_write_failed")


def _read_ready_host(organization_id: str) -> str | None:
    """The control plane's host for a ready warehouse, or None.

    Import is local so this module's importers do not pull the presentation package, and so a
    worker that never guards a managed source never loads it.
    """
    if not hogtower.is_configured():
        return None

    try:
        response = hogtower.request("GET", organization_id, "/warehouse/status", timeout=_CONTROL_PLANE_TIMEOUT_SECONDS)
    except http_requests.Timeout:
        logger.warning("managed_warehouse_target_timeout", organization_id=organization_id)
        return None
    except http_requests.RequestException:
        logger.warning("managed_warehouse_target_unreachable", organization_id=organization_id)
        return None
    except Exception:
        # A control-plane response the adapter cannot translate is not a verdict on the
        # organization. Deny, and keep the failure out of the caller's connect.
        logger.exception("managed_warehouse_target_control_plane_error", organization_id=organization_id)
        return None

    if response.status_code != 200 or not isinstance(response.body, dict):
        return None
    return _host_from_status(organization_id, response.body)


def _host_from_status(organization_id: str, body: dict[str, Any]) -> str | None:
    """The ready host from a status body, refusing one that names another organization."""
    response_org = body.get("org_id")
    if response_org is not None and str(response_org) != str(organization_id):
        logger.warning(
            "managed_warehouse_target_org_mismatch",
            requested_organization_id=str(organization_id),
            response_organization_id=str(response_org),
        )
        return None

    if body.get("state") != "ready":
        return None

    connection = body.get("connection")
    if not isinstance(connection, dict):
        return None
    host = connection.get("host")
    return host if isinstance(host, str) and host.strip() else None
