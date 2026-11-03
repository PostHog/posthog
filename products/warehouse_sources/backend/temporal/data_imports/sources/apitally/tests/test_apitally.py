from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally import (
    _format_apitally_datetime,
    _incremental_window,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.source import ApitallySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.apitally import (
    ApitallySourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ApitallySource(), ApitallySourceConfig(api_key="key"))


class TestFormatApitallyDatetime:
    def test_caps_future_datetime_to_now(self) -> None:
        far_future = datetime(2999, 1, 1, tzinfo=UTC)
        formatted = _format_apitally_datetime(far_future)
        assert formatted != "2999-01-01T00:00:00Z"
        assert datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%SZ") <= datetime.now(UTC).replace(tzinfo=None)

    def test_passes_through_already_formatted_string(self) -> None:
        # Our own `initial_value` seed round-trips through `convert` on the first sync.
        assert _format_apitally_datetime("1970-01-01T00:00:00Z") == "1970-01-01T00:00:00Z"


class TestIncrementalWindow:
    def test_shape(self) -> None:
        window = _incremental_window("timestamp")

        assert window["cursor_path"] == "timestamp"
        assert window["start_param"] == "start"
        assert window["end_param"] == "end"
        assert window["initial_value"] == "1970-01-01T00:00:00Z"
        assert window["end_value"] is not None
        assert window["convert"] is _format_apitally_datetime


class TestGetResource:
    @parameterized.expand(["Consumers", "Endpoints", "Traffic", "RequestLogs"])
    def test_rejects_fanout_endpoints(self, endpoint: str) -> None:
        try:
            get_resource(endpoint, should_use_incremental_field=False)
            raise AssertionError("expected ValueError for fan-out endpoint")
        except ValueError as exc:
            assert endpoint in str(exc)


class TestValidateCredentials:
    def test_valid_key(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": []})]) as network:
            result = validate_credentials("valid-key")

        assert result == (True, None)
        assert [request.path for request in network.requests_log] == ["/v1/apps"]
        assert network.requests_log[0].headers["api-key"] == "valid-key"

    def test_forbidden_reports_premium_plan_requirement(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]):
            result = validate_credentials("key")

        assert result == (
            False,
            "Your Apitally plan does not include API access. Upgrade to the Premium plan to enable it.",
        )

    @parameterized.expand([(503,)])
    def test_other_error_uses_response_detail(self, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={"detail": "server exploded"}))):
            result = validate_credentials("key")

        assert result == (False, "server exploded")


class TestApitallySourceTopLevel:
    def test_apps_builds_response(self) -> None:
        result = _driver().run("Apps", [ScriptedResponse(json={"data": []})])

        assert result.raised is None
        resp = result.response
        assert resp is not None
        assert resp.name == "Apps"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]


class TestApitallyFanout:
    @parameterized.expand(
        [
            ("Consumers", {"id": "c1"}),
            ("Traffic", {"period_start": "2025-01-01T00:00:00Z"}),
            ("RequestLogs", {"request_uuid": "r1"}),
        ]
    )
    def test_fanout_row_format_renames_parent_id_to_app_id(self, endpoint: str, child_row: dict[str, Any]) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"data": [{"id": "1"}]}), ScriptedResponse(json=[child_row])],
        )

        assert result.raised is None
        child_path = "request-logs" if endpoint == "RequestLogs" else endpoint.lower()
        assert result.paths == ["/v1/apps", f"/v1/apps/1/{child_path}"]
        assert len(result.rows) == 1
        row = result.rows[0]
        assert row["app_id"] == "1"
        assert "_Apps_id" not in row

    @parameterized.expand(["Consumers", "Endpoints", "Traffic", "RequestLogs"])
    def test_fanout_unwraps_parent_data_envelope(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"data": [{"id": "1"}]}), ScriptedResponse(json=[])],
        )

        assert result.raised is None
        assert result.paths[0] == "/v1/apps"
        assert result.paths[1].startswith("/v1/apps/1/")

    def test_traffic_incremental_passes_window_factory(self) -> None:
        result = _driver().run(
            "Traffic",
            [ScriptedResponse(json={"data": [{"id": "1"}]}), ScriptedResponse(json=[])],
            db_incremental_field_last_value=datetime(2025, 1, 1, tzinfo=UTC),
            incremental_field="period_end",
        )

        assert result.raised is None
        assert result.paths == ["/v1/apps", "/v1/apps/1/traffic"]
        assert result.params("start") == [None, "2025-01-01T00:00:00Z"]
        assert result.requests[1].param("end") is not None
