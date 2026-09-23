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
from products.managed_warehouse.backend.metrics import record_trino_connection
from products.managed_warehouse.backend.trino_target import get_ready_trino_connection_target
from products.warehouse_sources.backend.facade import source_management

if TYPE_CHECKING:
    from trino.dbapi import Connection

DUCKGRES_ROOT_LOGIN = "root"


def _trino_login_for(principal: str, duckgres_username: str) -> str:
    """Name the Trino login the organization's stored duckgres credential authenticates.

    The control plane projects each duckgres login into one flat, cell-wide password file:
    the root login as the bare principal, every other login as "<principal>.<login>". A
    duckgres username on its own is never a login there.
    """
    if duckgres_username == DUCKGRES_ROOT_LOGIN:
        return principal
    return f"{principal}.{duckgres_username}"


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
    if not root_connection.username or not root_connection.password:
        raise ManagedWarehouseTrinoConnectionUnavailable(
            "The organization does not have a stored managed warehouse credential"
        )

    if target.principal is None:
        raise ManagedWarehouseTrinoConnectionUnavailable(
            "The managed Trino target does not name the organization's Trino principal"
        )

    username = _trino_login_for(target.principal, root_connection.username)
    # The target advertises the login it expects either as that principal or as the bare
    # duckgres username behind it. Anything else names an identity with no stored secret,
    # and pairing it with this one only produces a 401 on the first statement.
    if target.username not in (username, root_connection.username):
        raise ManagedWarehouseTrinoConnectionUnavailable(
            f"The managed Trino target expects the login {target.username!r}, "
            f"and the organization only has a stored credential for {username!r}"
        )

    return ManagedWarehouseTrinoConnection(
        host=target.host,
        port=target.port,
        catalog=target.catalog,
        username=username,
        password=root_connection.password,
    )


def _is_trino_unauthorized(error: Exception) -> bool:
    # Match the driver's HTTP 401 form ("error 401: ..."), not a bare "401": a Trino query
    # error's text carries a query ID whose time part can hold "401".
    return "error 401" in str(error).lower()


@contextmanager
def connect_managed_warehouse_trino(organization_id: str) -> Iterator[Connection]:
    from trino.auth import BasicAuthentication  # noqa: PLC0415 -- keeps the optional driver off startup paths
    from trino.dbapi import connect  # noqa: PLC0415 -- keeps the optional driver off startup paths
    from trino.exceptions import HttpError  # noqa: PLC0415 -- keeps the optional driver off startup paths

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
        status = "failed"
        try:
            yield connection
            status = "succeeded"
        except HttpError as error:
            # Trino authenticates on the first statement, not at connect time, so a rejected
            # credential surfaces here rather than at connect.
            if not _is_trino_unauthorized(error):
                raise
            status = "unauthorized"
            raise ManagedWarehouseTrinoConnectionUnavailable(
                f"Trino rejected the login {config.username!r} for the organization's managed warehouse. "
                "Reset the managed warehouse password to store a current credential."
            ) from error
        finally:
            record_trino_connection(status)
            connection.close()
