from typing import Any, cast

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.strato import StratoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.strato.source import StratoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato import (
    get_resource,
    validate_credentials,
)


def _driver(api_token: str = "token") -> SourceDriver:
    return SourceDriver(StratoSource(), StratoSourceConfig(api_token=api_token))


class TestValidateCredentials:
    def test_ip_restricted_token_points_to_the_restriction(self) -> None:
        with scripted_network([ScriptedResponse(status=406, json={})]):
            valid, message = validate_credentials("token")

        assert valid is False
        assert message is not None
        assert "IP" in message

    @parameterized.expand([(503,)])
    def test_other_error_uses_response_message(self, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={"message": "Internal error"}))):
            result = validate_credentials("token")

        assert result == (False, "Internal error")


class TestGetResource:
    def test_rejects_fanout_endpoint(self) -> None:
        try:
            get_resource("Snapshots")
            raise AssertionError("expected ValueError for fan-out endpoint")
        except ValueError as exc:
            assert "Snapshots" in str(exc)


class TestSecretScrubbing:
    def test_server_rows_drop_the_initial_root_password(self) -> None:
        data_map = get_resource("Servers")["data_map"]
        assert data_map is not None

        row = cast(dict[str, Any], data_map({"id": "srv1", "name": "web-1", "first_password": "hunter2"}))

        assert "first_password" not in row
        assert row["id"] == "srv1"
        assert row["name"] == "web-1"

    def test_user_rows_drop_the_api_key_but_keep_other_api_settings(self) -> None:
        data_map = get_resource("Users")["data_map"]
        assert data_map is not None

        row = cast(
            dict[str, Any],
            data_map({"id": "u1", "api": {"active": True, "key": "secret-token", "allowed_ips": ["1.2.3.4"]}}),
        )

        assert row["api"] == {"active": True, "allowed_ips": ["1.2.3.4"]}

    @parameterized.expand(
        [
            ("Servers", {"id": "srv1"}),
            ("Users", {"id": "u1"}),
            ("Users", {"id": "u1", "api": None}),
        ]
    )
    def test_rows_without_secret_fields_pass_through(self, endpoint: str, row: dict[str, Any]) -> None:
        data_map = get_resource(endpoint)["data_map"]
        assert data_map is not None

        assert data_map(dict(row)) == row


class TestStratoSourceTopLevel:
    def test_servers_builds_response(self) -> None:
        resp = _driver().run("Servers", []).response

        assert resp is not None
        assert resp.name == "Servers"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["creation_date"]


class TestStratoFanout:
    def test_client_sends_token_header_and_refuses_redirects(self) -> None:
        result = _driver("secret-token").run(
            "Snapshots",
            [ScriptedResponse(json=[{"id": "srv1"}]), ScriptedResponse(json=[{"id": "snap1"}])],
        )

        assert result.raised is None
        assert result.rows == [{"id": "snap1", "server_id": "srv1"}]
        assert all(request.headers["x-token"] == "secret-token" for request in result.requests)
        # STRATO list endpoints take no page-size param; sending one would be undocumented.
        assert result.queries == [{}, {}]

    def test_a_redirect_is_never_followed(self) -> None:
        redirect = ScriptedResponse(status=302, headers={"Location": "https://evil.example.com/v1/servers"})

        result = _driver("secret-token").run("Snapshots", [redirect])

        assert all("evil.example.com" not in url for url in result.urls)
