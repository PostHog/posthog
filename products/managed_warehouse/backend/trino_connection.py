from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import requests

from products.managed_warehouse.backend.facade.api import get_duckgres_query_server_config
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTrinoConnection,
    ManagedWarehouseTrinoConnectionUnavailable,
)
from products.managed_warehouse.backend.trino_target import get_ready_trino_connection_target
from products.warehouse_sources.backend.facade import source_management

if TYPE_CHECKING:
    from trino.dbapi import Connection


def resolve_managed_warehouse_trino_connection(organization_id: str) -> ManagedWarehouseTrinoConnection:
    target = get_ready_trino_connection_target(organization_id)
    if target is None:
        raise ManagedWarehouseTrinoConnectionUnavailable(
            "The organization does not have a ready managed Trino connection"
        )

    try:
        root_connection = get_duckgres_query_server_config(organization_id)
    except ValueError as error:
        raise ManagedWarehouseTrinoConnectionUnavailable(
            "The organization does not have a stored managed warehouse credential"
        ) from error
    if not root_connection.password:
        raise ManagedWarehouseTrinoConnectionUnavailable(
            "The organization does not have a stored managed warehouse credential"
        )

    return ManagedWarehouseTrinoConnection(
        host=target.host,
        port=target.port,
        catalog=target.catalog,
        username=target.username,
        password=root_connection.password,
    )


@contextmanager
def connect_managed_warehouse_trino(organization_id: str) -> Iterator[Connection]:
    from trino.auth import BasicAuthentication  # noqa: PLC0415 -- keeps the optional driver off startup paths
    from trino.dbapi import connect  # noqa: PLC0415 -- keeps the optional driver off startup paths

    config = resolve_managed_warehouse_trino_connection(organization_id)
    with requests.Session() as http_session:
        # Only known hosted Trino endpoints bypass the proxy's private-IP restrictions.
        if source_management.is_posthog_managed_trino_host(config.host) and config.port == 443:
            http_session.trust_env = False
        connection = connect(
            host=config.host,
            port=config.port,
            user=config.username,
            catalog=config.catalog,
            http_scheme="https",
            auth=BasicAuthentication(config.username, config.password),
            request_timeout=60,
            verify=True,
            http_session=http_session,
        )
        try:
            yield connection
        finally:
            connection.close()
