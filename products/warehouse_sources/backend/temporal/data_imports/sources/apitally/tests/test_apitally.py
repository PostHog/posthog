from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally import (
    _format_apitally_datetime,
    _incremental_window,
    apitally_source,
    get_resource,
    validate_credentials,
)


class _FakeDltResource:
    """Lightweight stand-in for a DltResource returned by rest_api_resources.

    ``process_parent_data_item`` injects parent fields as ``_<parent_resource>_<field>``
    (see ``make_parent_key_name``), so test data should include those prefixed keys to
    exercise the row mappers.
    """

    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


def _response(status_code: int = 200, json_body: Any = None, text: str = "") -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else {}
    response.text = text
    return response


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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.make_tracked_session")
    def test_valid_key(self, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(200, {"data": []})

        result = validate_credentials("valid-key")

        assert result == (True, None)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.make_tracked_session")
    def test_invalid_key(self, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(401)

        result = validate_credentials("bad-key")

        assert result == (False, "Invalid Apitally API key.")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.make_tracked_session")
    def test_forbidden_reports_premium_plan_requirement(self, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(403)

        result = validate_credentials("key")

        assert result == (
            False,
            "Your Apitally plan does not include API access. Upgrade to the Premium plan to enable it.",
        )

    @parameterized.expand([(500,), (503,)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.make_tracked_session")
    def test_other_error_uses_response_detail(self, status_code: int, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(status_code, {"detail": "server exploded"})

        result = validate_credentials("key")

        assert result == (False, "server exploded")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.make_tracked_session")
    def test_network_error_returns_false(self, mock_make_session) -> None:
        from requests.exceptions import ConnectionError

        mock_make_session.return_value.get.side_effect = ConnectionError("boom")

        result = validate_credentials("key")

        assert result == (False, "boom")


class TestApitallySourceTopLevel:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.rest_api_resource")
    def test_apps_builds_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()

        resp = apitally_source(
            api_key="key",
            endpoint="Apps",
            team_id=1,
            job_id="job-1",
        )

        assert resp.name == "Apps"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]


class TestApitallyFanout:
    @parameterized.expand(
        [
            ("Consumers", {"id": "c1", "_Apps_id": "1"}),
            ("Traffic", {"period_start": "2025-01-01T00:00:00Z", "_Apps_id": "1"}),
            ("RequestLogs", {"request_uuid": "r1", "_Apps_id": "1"}),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_fanout_row_format_renames_parent_id_to_app_id(self, endpoint, child_row, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("Apps", [{"id": "1"}]),
            _FakeDltResource(endpoint, [child_row]),
        ]

        resp = apitally_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["app_id"] == "1"
        assert "_Apps_id" not in row

    @parameterized.expand(["Consumers", "Endpoints", "Traffic", "RequestLogs"])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.build_dependent_resource"
    )
    def test_fanout_unwraps_parent_data_envelope(self, endpoint, mock_build) -> None:
        mock_build.return_value = iter([])

        apitally_source(api_key="key", endpoint=endpoint, team_id=1, job_id="job-1")

        _, kwargs = mock_build.call_args
        assert kwargs["parent_endpoint_extra"] == {"data_selector": "data"}

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.build_dependent_resource"
    )
    def test_traffic_incremental_passes_window_factory(self, mock_build) -> None:
        mock_build.return_value = iter([])

        apitally_source(
            api_key="key",
            endpoint="Traffic",
            team_id=1,
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 1, tzinfo=UTC),
            incremental_field="period_end",
        )

        _, kwargs = mock_build.call_args
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "period_end"
        assert kwargs["incremental_config_factory"] is _incremental_window
