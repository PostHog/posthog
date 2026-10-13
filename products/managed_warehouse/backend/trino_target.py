from __future__ import annotations

from typing import cast

import structlog
from rest_framework import status

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.presentation import views as provisioning_views

logger = structlog.get_logger(__name__)


@frozen
class _ReadyTrinoConnectionTarget:
    host: str
    port: int
    catalog: str
    username: str


def _nonempty_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _ready_trino_status(organization_id: str) -> dict[str, object] | None:
    response = provisioning_views._request("GET", organization_id, "/trino", require_enabled=False)
    if not status.is_success(response.status_code) or not isinstance(response.data, dict):
        return None
    if response.data.get("enabled") is not True:
        return None

    trino_status = response.data.get("status")
    if not isinstance(trino_status, dict) or trino_status.get("state") != "ready":
        return None
    response_org = trino_status.get("org")
    if str(response_org) != str(organization_id):
        logger.warning(
            "refusing_trino_target_for_mismatched_organization",
            requested_organization_id=str(organization_id),
            response_organization_id=str(response_org),
        )
        return None
    return cast(dict[str, object], trino_status)


def get_ready_trino_connection_target(organization_id: str) -> _ReadyTrinoConnectionTarget | None:
    trino_status = _ready_trino_status(organization_id)
    if trino_status is None:
        return None

    catalog = _nonempty_string(trino_status.get("trino_catalog_name") or trino_status.get("catalog"))
    connection = trino_status.get("connection")
    if catalog is None or not isinstance(connection, dict):
        return None

    host = _nonempty_string(connection.get("host"))
    username = _nonempty_string(connection.get("username"))
    port = connection.get("port")
    if (
        host is None
        or username is None
        or isinstance(port, bool)
        or not isinstance(port, int)
        or not 1 <= port <= 65535
    ):
        return None

    return _ReadyTrinoConnectionTarget(host=host, port=port, catalog=catalog, username=username)
