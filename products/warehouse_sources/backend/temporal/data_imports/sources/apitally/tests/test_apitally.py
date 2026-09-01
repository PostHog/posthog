from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit

from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally import (
    _client_config,
    _format_apitally_datetime,
    _incremental_window,
    apitally_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apitally.settings import APITALLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
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


class _FakePreparedRequest:
    def __init__(self, url: str) -> None:
        self.url = url
        self.headers: dict[str, str] = {}


class _FakeResponse:
    def __init__(self, body: Any) -> None:
        self._body = body
        self.status_code = 200
        self.is_redirect = False

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        return None


class _EnvelopeParentSession:
    """Fake `requests` session: the parent `/v1/apps` returns an enveloped body, each child a bare list."""

    def __init__(self, apps: list[dict[str, Any]], children_by_app: dict[str, list[dict[str, Any]]]) -> None:
        self.headers: dict[str, str] = {}
        self._apps = apps
        self._children_by_app = children_by_app
        self.requested_paths: list[str] = []

    def prepare_request(self, request: Any) -> _FakePreparedRequest:
        return _FakePreparedRequest(request.url)

    def send(self, prepared: _FakePreparedRequest, allow_redirects: bool = True, timeout: Any = None) -> _FakeResponse:
        path = urlsplit(prepared.url).path
        self.requested_paths.append(path)
        if path == "/v1/apps":
            return _FakeResponse({"data": self._apps})
        # /v1/apps/{app_id}/consumers
        app_id = path.split("/")[3]
        return _FakeResponse(self._children_by_app.get(app_id, []))


def _response(status_code: int = 200, json_body: Any = None, text: str = "") -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else {}
    response.text = text
    return response


class TestFormatApitallyDatetime:
    def test_formats_naive_datetime_as_utc(self) -> None:
        assert _format_apitally_datetime(datetime(2025, 5, 14, 0, 0, 0)) == "2025-05-14T00:00:00Z"

    def test_formats_aware_datetime_converted_to_utc(self) -> None:
        aware = datetime(2025, 5, 14, 5, 0, 0, tzinfo=UTC)
        assert _format_apitally_datetime(aware) == "2025-05-14T05:00:00Z"

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
    def test_apps_shape(self) -> None:
        resource = get_resource("Apps", should_use_incremental_field=False)

        assert resource["name"] == "Apps"
        assert resource["write_disposition"] == "replace"
        endpoint = cast(dict[str, Any], resource["endpoint"])
        assert endpoint["path"] == "/v1/apps"
        assert endpoint["data_selector"] == "data"
        assert isinstance(endpoint["paginator"], SinglePagePaginator)
        assert "params" not in endpoint

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

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.build_dependent_resource"
    )
    def test_endpoints_fanout_overrides_paginator_to_single_page(self, mock_build) -> None:
        mock_build.return_value = iter([])

        apitally_source(api_key="key", endpoint="Endpoints", team_id=1, job_id="job-1")

        _, kwargs = mock_build.call_args
        assert kwargs["page_size_param"] is None
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], SinglePagePaginator)

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
    def test_consumers_fanout_keeps_cursor_pagination(self, mock_build) -> None:
        mock_build.return_value = iter([])

        apitally_source(api_key="key", endpoint="Consumers", team_id=1, job_id="job-1")

        _, kwargs = mock_build.call_args
        assert kwargs["page_size_param"] == "limit"
        assert kwargs["child_endpoint_extra"] is None

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

    def test_fanout_extracts_enveloped_parent_and_fetches_children(self) -> None:
        # `/v1/apps` wraps its rows in a `{"data": [...]}` envelope. Drive the real fan-out
        # through a fake transport: without `parent_data_selector` the parent page is the
        # envelope itself, so `process_parent_data_item` cannot find "id" and every child
        # sync fails before it fetches a row.
        session = _EnvelopeParentSession(
            apps=[{"id": "app-1"}, {"id": "app-2"}],
            children_by_app={
                "app-1": [{"id": "consumer-1"}],
                "app-2": [{"id": "consumer-2"}, {"id": "consumer-3"}],
            },
        )
        client_config = cast(Any, {**_client_config("key"), "session": session})

        resource = build_dependent_resource(
            endpoint_configs=APITALLY_ENDPOINTS,
            child_endpoint="Consumers",
            fanout=cast(Any, APITALLY_ENDPOINTS["Consumers"].fanout),
            client_config=client_config,
            path_format_values={},
            team_id=1,
            job_id="job-1",
            db_incremental_field_last_value=None,
        )

        rows = [row for page in cast(Any, resource) for row in page]

        assert [(row["app_id"], row["id"]) for row in rows] == [
            ("app-1", "consumer-1"),
            ("app-2", "consumer-2"),
            ("app-2", "consumer-3"),
        ]
        assert session.requested_paths == [
            "/v1/apps",
            "/v1/apps/app-1/consumers",
            "/v1/apps/app-2/consumers",
        ]

    def test_client_config_uses_cursor_paginator_and_api_key_header(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.apitally.apitally.build_dependent_resource"
        ) as mock_build:
            mock_build.return_value = iter([])
            apitally_source(api_key="secret-key", endpoint="Consumers", team_id=1, job_id="job-1")

            _, kwargs = mock_build.call_args
            client_config = kwargs["client_config"]
            assert isinstance(client_config["paginator"], JSONResponseCursorPaginator)
            assert client_config["auth"] == {
                "type": "api_key",
                "name": "Api-Key",
                "api_key": "secret-key",
                "location": "header",
            }
