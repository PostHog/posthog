from typing import Any, cast

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.strato._config import StratoSourceConfig
from products.warehouse_sources.sources.strato.source import StratoSource
from products.warehouse_sources.sources.strato.strato import get_resource, validate_credentials


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


class TestUsages:
    def test_report_is_flattened_to_one_row_per_resource_and_requests_a_period(self) -> None:
        report = {
            "SERVERS": [{"id": "srv1", "name": "web-1", "services": [{"type": "CPU", "usage": 10}]}],
            "IMAGES": [{"id": "img1", "name": "base", "services": []}],
            "PUBLIC_IPS": [{"name": "203.0.113.7", "services": [{"type": "UNUSED_IP", "usage": 5}]}],
        }

        result = _driver().run("Usages", [ScriptedResponse(json=report)])

        assert result.raised is None
        assert result.queries == [{"period": ("LAST_365D",)}]
        assert result.paths == ["/v1/usages"]
        assert [(row["resource_type"], row["resource_key"]) for row in result.rows] == [
            ("SERVERS", "srv1"),
            ("IMAGES", "img1"),
            ("PUBLIC_IPS", "203.0.113.7"),
        ]
        assert result.rows[0]["services"] == [{"type": "CPU", "usage": 10}]
        assert result.response is not None
        assert result.response.primary_keys == ["resource_type", "resource_key"]

    @parameterized.expand(
        [
            ("empty_report", {}, []),
            ("empty_resource_lists", {"SERVERS": [], "IMAGES": []}, []),
            ("non_list_value_is_skipped", {"SERVERS": None, "IMAGES": [{"id": "img1"}]}, [("IMAGES", "img1")]),
            ("non_dict_resource_is_skipped", {"SERVERS": ["oops", {"id": "srv1"}]}, [("SERVERS", "srv1")]),
            (
                "id_wins_over_name",
                {"SHARED_STORAGES": [{"id": "st1", "name": "data"}, {"name": "backup"}]},
                [("SHARED_STORAGES", "st1"), ("SHARED_STORAGES", "backup")],
            ),
        ]
    )
    def test_flatten_edge_cases(self, _name: str, report: dict[str, Any], expected: list[tuple[str, str]]) -> None:
        data_map = get_resource("Usages")["data_map"]
        assert data_map is not None

        rows = cast(list[dict[str, Any]], data_map(report))

        assert [(row["resource_type"], row["resource_key"]) for row in rows] == expected


class TestServerMonitoring:
    def test_fans_out_per_server_with_a_period_and_skips_deleted_servers(self) -> None:
        result = _driver().run(
            "ServerMonitoring",
            [
                ScriptedResponse(json=[{"id": "srv1"}, {"id": "srv2"}]),
                ScriptedResponse(json={"id": "srv1", "name": "web-1", "cpu": {"data": [{"used_percent": 3}]}}),
                ScriptedResponse(status=404, json={"type": "NOT_FOUND", "message": "Server not found"}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v1/servers", "/v1/monitoring_center/srv1", "/v1/monitoring_center/srv2"]
        assert result.queries[1:] == [{"period": ("LAST_30D",)}, {"period": ("LAST_30D",)}]
        assert result.rows == [
            {"id": "srv1", "name": "web-1", "cpu": {"data": [{"used_percent": 3}]}, "server_id": "srv1"}
        ]
