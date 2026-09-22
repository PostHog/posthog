import pytest
from unittest import mock

from rest_framework.response import Response

from products.managed_warehouse.backend.facade.contracts import (
    DuckgresQueryServerConfig,
    ManagedWarehouseTrinoConnectionUnavailable,
)
from products.managed_warehouse.backend.trino_connection import (
    connect_managed_warehouse_trino,
    resolve_managed_warehouse_trino_connection,
)


def _ready_response(**connection_overrides: object) -> Response:
    return Response(
        {
            "enabled": True,
            "status": {
                "org": "org-1",
                "state": "ready",
                "trino_catalog_name": "org_catalog",
                "connection": {
                    "host": "trino.postwh.com",
                    "port": 8443,
                    "username": "org_database",
                    **connection_overrides,
                },
            },
        },
        status=200,
    )


def _root_connection(password: str = "root-secret") -> DuckgresQueryServerConfig:
    return DuckgresQueryServerConfig(
        host="duckgres.postwh.com",
        port=5432,
        flight_port=8815,
        database="ducklake",
        username="root",
        password=password,
    )


class TestResolveManagedWarehouseTrinoConnection:
    def test_combines_the_control_plane_target_with_the_existing_root_secret(self) -> None:
        with (
            mock.patch(
                "products.managed_warehouse.backend.presentation.views._request",
                return_value=_ready_response(),
            ) as request,
            mock.patch(
                "products.managed_warehouse.backend.trino_connection.get_duckgres_query_server_config",
                return_value=_root_connection(),
            ),
        ):
            connection = resolve_managed_warehouse_trino_connection("org-1")

        assert connection.host == "trino.postwh.com"
        assert connection.port == 8443
        assert connection.catalog == "org_catalog"
        assert connection.username == "org_database"
        assert connection.password == "root-secret"
        assert "root-secret" not in repr(connection)
        request.assert_called_once_with("GET", "org-1", "/trino", require_enabled=False)

    @pytest.mark.parametrize(
        "response",
        [
            Response({"enabled": False}, status=200),
            Response({"enabled": True, "status": {"org": "org-1", "state": "pending"}}, status=200),
            Response(
                {
                    "enabled": True,
                    "status": {
                        "state": "ready",
                        "trino_catalog_name": "catalog",
                        "connection": {"host": "trino.postwh.com", "port": 8443, "username": "org_database"},
                    },
                },
                status=200,
            ),
            Response(
                {
                    "enabled": True,
                    "status": {
                        "org": "another-org",
                        "state": "ready",
                        "trino_catalog_name": "catalog",
                        "connection": {"host": "trino.postwh.com", "port": 8443, "username": "org_database"},
                    },
                },
                status=200,
            ),
            _ready_response(host=""),
            _ready_response(port=0),
            _ready_response(username=""),
        ],
    )
    def test_rejects_an_unusable_or_cross_organization_target(self, response: Response) -> None:
        with mock.patch("products.managed_warehouse.backend.presentation.views._request", return_value=response):
            with pytest.raises(ManagedWarehouseTrinoConnectionUnavailable, match="ready managed Trino connection"):
                resolve_managed_warehouse_trino_connection("org-1")

    def test_rejects_a_missing_stored_root_secret(self) -> None:
        with (
            mock.patch(
                "products.managed_warehouse.backend.presentation.views._request",
                return_value=_ready_response(),
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_connection.get_duckgres_query_server_config",
                return_value=_root_connection(password=""),
            ),
        ):
            with pytest.raises(ManagedWarehouseTrinoConnectionUnavailable, match="stored managed warehouse credential"):
                resolve_managed_warehouse_trino_connection("org-1")


def test_connect_managed_warehouse_trino_enforces_verified_https_and_closes() -> None:
    driver_connection = mock.MagicMock()
    authentication = mock.sentinel.authentication

    with (
        mock.patch(
            "products.managed_warehouse.backend.trino_connection.resolve_managed_warehouse_trino_connection",
            return_value=mock.Mock(
                host="trino.postwh.com",
                port=8443,
                catalog="org_catalog",
                username="org_database",
                password="root-secret",
            ),
        ),
        mock.patch("trino.auth.BasicAuthentication", return_value=authentication) as basic_authentication,
        mock.patch("trino.dbapi.connect", return_value=driver_connection) as connect,
    ):
        with connect_managed_warehouse_trino("org-1") as connection:
            assert connection is driver_connection

    basic_authentication.assert_called_once_with("org_database", "root-secret")
    connect.assert_called_once_with(
        host="trino.postwh.com",
        port=8443,
        user="org_database",
        catalog="org_catalog",
        http_scheme="https",
        auth=authentication,
        request_timeout=60,
        verify=True,
    )
    driver_connection.close.assert_called_once_with()
