import os

import pytest
from unittest import mock

import requests
from rest_framework.response import Response

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTrinoConnectionUnavailable
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


class TestResolveManagedWarehouseTrinoConnection:
    def test_combines_the_control_plane_target_with_the_stored_trino_secret(self) -> None:
        with (
            mock.patch(
                "products.managed_warehouse.backend.presentation.views._request",
                return_value=_ready_response(),
            ) as request,
            mock.patch(
                "products.managed_warehouse.backend.trino_connection.get_managed_warehouse_trino_password",
                return_value="trino-secret",
            ),
        ):
            connection = resolve_managed_warehouse_trino_connection("org-1")

        assert connection.host == "trino.postwh.com"
        assert connection.port == 8443
        assert connection.catalog == "org_catalog"
        assert connection.username == "org_database"
        assert connection.password == "trino-secret"
        assert "trino-secret" not in repr(connection)
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

    def test_rejects_a_missing_stored_trino_secret(self) -> None:
        with (
            mock.patch(
                "products.managed_warehouse.backend.presentation.views._request",
                return_value=_ready_response(),
            ),
            mock.patch(
                "products.managed_warehouse.backend.trino_connection.get_managed_warehouse_trino_password",
                return_value="",
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
        http_session=mock.ANY,
    )
    driver_connection.close.assert_called_once_with()


@pytest.mark.parametrize(
    "host,port,bypass_proxy",
    [
        ("trino.dw.us.postwh.com", 443, True),
        ("TRINO.DW.US.POSTWH.COM.", 443, True),
        ("trino.dw.us.postwh.com", 8443, False),
        ("trino.example.com", 443, False),
    ],
)
def test_managed_trino_requests_bypass_environment_proxies_only_for_known_hosts(
    host: str, port: int, bypass_proxy: bool
) -> None:
    proxy_url = "http://proxy.example.com:4750"
    with (
        mock.patch.dict(os.environ, {"HTTPS_PROXY": proxy_url, "NO_PROXY": ""}, clear=True),
        mock.patch(
            "products.managed_warehouse.backend.presentation.views._request",
            return_value=_ready_response(host=host, port=port),
        ),
        mock.patch(
            "products.managed_warehouse.backend.trino_connection.get_managed_warehouse_trino_password",
            return_value="root-secret",
        ),
        mock.patch("requests.adapters.HTTPAdapter.send", side_effect=RuntimeError("network boundary")) as send,
    ):
        with pytest.raises(RuntimeError, match="network boundary"):
            with connect_managed_warehouse_trino("org-1") as connection:
                connection.cursor().execute("SELECT 1")

        send.assert_called_once()
        request = send.call_args.args[0]
        assert request.url == f"https://{host.lower()}:{port}/v1/statement"
        assert request.headers["Authorization"].startswith("Basic ")
        assert send.call_args.kwargs["proxies"].get("https") == (None if bypass_proxy else proxy_url)
        assert send.call_args.kwargs["verify"] is True
        assert send.call_args.kwargs["timeout"] == 60

        with requests.Session() as ordinary_session:
            settings = ordinary_session.merge_environment_settings("https://example.com", {}, False, True, None)
        assert settings["proxies"]["https"] == proxy_url
