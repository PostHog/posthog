"""Whether duckgres has an organization, learned from how it answers a connection."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

import psycopg
import structlog

from posthog.redis import get_client

from products.managed_warehouse.backend.common import is_dev_mode
from products.managed_warehouse.backend.facade.contracts import (
    DuckgresConnectionRefused,
    DuckgresOrganizationUnavailable,
)
from products.managed_warehouse.backend.storage import connect_to_duckgres

if TYPE_CHECKING:
    import redis

    from products.managed_warehouse.backend.models import DuckgresServer

logger = structlog.get_logger(__name__)

_DUCKGRES_HOSTNAME_REFUSAL = re.compile(r"this server requires connecting via ([^\n]+)")
_DUCKGRES_MANAGED_SUFFIX = re.compile(r"<org-id>(\S+)")

# A Redis that stops replying must not hold the gate activity past its deadline.
PROBE_CACHE_SOCKET_TIMEOUT_SECONDS = 1.0
PROBE_APPLICATION_NAME = "ducklake-register-probe"
PROBE_CONNECT_TIMEOUT_SECONDS = 15
# An organization that connects does not lose its duckgres organization, so the answer stays for a day.
PROBE_AVAILABLE_CACHE_TIMEOUT_SECONDS = 24 * 60 * 60
# duckgres also sends the refusal while a control-plane replica has no config snapshot yet, or one that predates a new
# organization. A refusal is fast and allocates no worker, so a short cache limits how long a wrong answer lasts.
PROBE_REFUSED_CACHE_TIMEOUT_SECONDS = 10 * 60
# An unknown answer keeps duckgres. It is cached so that an organization with a cold worker does not time out the probe,
# and abandon a worker allocation, on every registration.
PROBE_UNKNOWN_CACHE_TIMEOUT_SECONDS = 60 * 60


class DuckgresOrganizationStatus(StrEnum):
    AVAILABLE = "available"
    REFUSED = "refused"
    UNKNOWN = "unknown"


def classify_duckgres_refusal(
    host: str, organization_id: str, error: psycopg.OperationalError
) -> DuckgresConnectionRefused | None:
    """The refusal that `error` carries, or None when duckgres did not refuse the hostname.

    duckgres sends "this server requires connecting via <hint>" both for a hostname that is not a managed warehouse
    hostname and for a managed hostname whose organization it does not have. The hint names each managed suffix, as in
    "<org-id>.dw.us.postwh.com". hogtower creates new warehouses without a duckgres organization, so their connections
    get the second refusal.
    """
    match = _DUCKGRES_HOSTNAME_REFUSAL.search(str(error))
    if match is None:
        return None
    hint = match[1].strip()
    if any(host.endswith(suffix) for suffix in _DUCKGRES_MANAGED_SUFFIX.findall(hint)):
        return DuckgresOrganizationUnavailable(
            f"duckgres has no organization for org {organization_id}, so it refuses the connection to {host}"
        )
    return DuckgresConnectionRefused(
        f"duckgres refused the connection to {host or 'the configured host'}, because it is not a managed warehouse "
        f"hostname. duckgres expects {hint}"
    )


def probe_duckgres_organization(server: DuckgresServer) -> DuckgresOrganizationStatus:
    """Ask duckgres, with a short connection, whether it has the organization of `server`.

    The answer is cached per organization: AVAILABLE for a day, REFUSED for ten minutes and UNKNOWN for an hour. The probe does nothing in dev mode, where
    connections come from environment variables and no organization is provisioned.
    """
    if is_dev_mode():
        return DuckgresOrganizationStatus.UNKNOWN

    organization_id = str(server.organization_id)
    cache_key = f"managed_warehouse:duckgres_organization_probe:{organization_id}"
    try:
        cached = _cache_client().get(cache_key)
    except Exception:
        logger.warning("managed_warehouse_duckgres_probe_cache_failure", exc_info=True)
        cached = None
    if isinstance(cached, bytes):
        cached = cached.decode()
    if cached in set(DuckgresOrganizationStatus):
        return DuckgresOrganizationStatus(cached)

    status = _probe_connection(server, organization_id)
    timeout = {
        DuckgresOrganizationStatus.AVAILABLE: PROBE_AVAILABLE_CACHE_TIMEOUT_SECONDS,
        DuckgresOrganizationStatus.REFUSED: PROBE_REFUSED_CACHE_TIMEOUT_SECONDS,
        DuckgresOrganizationStatus.UNKNOWN: PROBE_UNKNOWN_CACHE_TIMEOUT_SECONDS,
    }[status]
    try:
        _cache_client().set(cache_key, status.value, ex=timeout)
    except Exception:
        logger.warning("managed_warehouse_duckgres_probe_cache_failure", exc_info=True)
    return status


def _cache_client() -> redis.Redis:
    return get_client(
        socket_timeout=PROBE_CACHE_SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=PROBE_CACHE_SOCKET_TIMEOUT_SECONDS,
    )


def _probe_connection(server: DuckgresServer, organization_id: str) -> DuckgresOrganizationStatus:
    try:
        connect_to_duckgres(
            server,
            application_name=PROBE_APPLICATION_NAME,
            connect_timeout=PROBE_CONNECT_TIMEOUT_SECONDS,
        ).close()
    except psycopg.OperationalError as error:
        refusal = classify_duckgres_refusal(server.host, organization_id, error)
        if isinstance(refusal, DuckgresOrganizationUnavailable):
            return DuckgresOrganizationStatus.REFUSED
        logger.warning(
            "managed_warehouse_duckgres_probe_unknown",
            organization_id=organization_id,
            error=str(error),
            refused_for_other_host=refusal is not None,
        )
        return DuckgresOrganizationStatus.UNKNOWN
    except Exception as error:
        logger.warning(
            "managed_warehouse_duckgres_probe_unknown",
            organization_id=organization_id,
            error=str(error),
            error_type=type(error).__name__,
        )
        return DuckgresOrganizationStatus.UNKNOWN
    return DuckgresOrganizationStatus.AVAILABLE
