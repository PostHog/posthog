import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
import time_machine
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io import (
    IncidentIoResumeConfig,
    _build_params,
    _build_url,
    _format_filter_value,
    _params_from_url,
    incident_io_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import (
    ENDPOINTS,
    INCIDENT_IO_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the incident_io module.
INCIDENT_IO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
)


def _page_body(data_key: str, items: list[dict[str, Any]], after: str | None) -> dict[str, Any]:
    return {data_key: items, "pagination_meta": {"after": after, "page_size": 250}}


def _response(body: dict[str, Any], status_code: int = 200, retry_after: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    if retry_after is not None:
        resp.headers["Retry-After"] = retry_after
    return resp


def _make_manager(resume_state: IncidentIoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response], urls: list[str] | None = None) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        if urls is not None:
            urls.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(session: mock.MagicMock, responses: list[Response], endpoint: str, manager: mock.MagicMock, **kwargs):
    params = _wire(session, responses)
    response = incident_io_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)
    rows = [row for page in cast("Iterable[Any]", response.items()) for row in page]
    return rows, params


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (datetime(2024, 5, 1, 12, 30, tzinfo=UTC), "2024-05-01"),
            (datetime(2024, 5, 1, 12, 30), "2024-05-01"),
            (date(2024, 5, 1), "2024-05-01"),
            ("2024-05-01T12:30:00Z", "2024-05-01"),
            ("2024-05-01T12:30:00+00:00", "2024-05-01"),
            ("2024-05-01", "2024-05-01"),
            ("not-a-date", None),
            (1700000000, None),
        ],
    )
    def test_format_filter_value(self, value, expected):
        assert _format_filter_value(value) == expected


class TestBuildParams:
    def test_incidents_include_page_size_and_sort(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], None, None)
        assert params == {"page_size": 250, "sort_by": "created_at_oldest_first"}

    def test_incremental_filter_included_when_set(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], "updated_at", "2024-05-01")
        assert params["updated_at[gte]"] == "2024-05-01"

    def test_incremental_filter_omitted_without_value(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], "updated_at", None)
        assert "updated_at[gte]" not in params

    def test_non_paginated_endpoint_has_no_params(self):
        assert _build_params(INCIDENT_IO_ENDPOINTS["severities"], None, None) == {}

    @pytest.mark.parametrize("endpoint", ["alerts", "escalations"])
    def test_small_page_endpoints_use_capped_page_size(self, endpoint):
        params = _build_params(INCIDENT_IO_ENDPOINTS[endpoint], None, None)
        assert params == {"page_size": 50}


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/v1/severities", {}) == "https://api.incident.io/v1/severities"

    def test_drops_none_values_and_encodes_brackets(self):
        url = _build_url("/v2/incidents", {"page_size": 250, "after": None, "updated_at[gte]": "2024-05-01"})
        assert url == "https://api.incident.io/v2/incidents?page_size=250&updated_at%5Bgte%5D=2024-05-01"


class TestParamsFromUrl:
    def test_strips_after_and_keeps_filters(self):
        url = _build_url(
            "/v2/incidents",
            {"page_size": 250, "sort_by": "created_at_oldest_first", "updated_at[gte]": "2024-05-01", "after": "01H"},
        )
        params = _params_from_url(url)
        assert params == {
            "page_size": "250",
            "sort_by": "created_at_oldest_first",
            "updated_at[gte]": "2024-05-01",
        }

    def test_url_without_query(self):
        assert _params_from_url("https://api.incident.io/v1/severities") == {}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, True),
            (500, False),
        ],
    )
    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_status_mapping_at_source_create(self, mock_session, status_code, expected_valid):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, _ = validate_credentials("key")

        assert is_valid is expected_valid

    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_status_mapping_with_schema_name(self, mock_session, status_code, expected_valid):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, error = validate_credentials("key", schema_name="alerts")

        assert is_valid is expected_valid
        if status_code == 403:
            assert error is not None and "alerts" in error

    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_probes_incidents_with_minimal_page_at_source_create(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key")

        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.incident.io/v2/incidents?page_size=1"

    @pytest.mark.parametrize(
        "schema_name, expected_url",
        [
            ("severities", "https://api.incident.io/v1/severities"),
        ],
    )
    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_probe_url_per_schema(self, mock_session, schema_name, expected_url):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("key", schema_name=schema_name)

        url = mock_session.return_value.get.call_args.args[0]
        assert url == expected_url

    @pytest.mark.parametrize(
        "schema_name, parent_key, parent_rows, child_status, expected_urls, expected_valid",
        [
            (
                "catalog_entries",
                "catalog_types",
                [{"id": "T1"}],
                403,
                [
                    "https://api.incident.io/v3/catalog_types",
                    "https://api.incident.io/v3/catalog_types",
                    "https://api.incident.io/v3/catalog_entries?catalog_type_id=T1&page_size=1",
                ],
                False,
            ),
            (
                "custom_field_options",
                "custom_fields",
                [{"id": "F1"}],
                200,
                [
                    "https://api.incident.io/v2/custom_fields",
                    "https://api.incident.io/v2/custom_fields",
                    "https://api.incident.io/v1/custom_field_options?custom_field_id=F1&page_size=1",
                ],
                True,
            ),
            # Schedule entries take no page-size param, so the child probe sends only the parent id.
            (
                "schedule_entries",
                "schedules",
                [{"id": "S1"}],
                200,
                [
                    "https://api.incident.io/v2/schedules?page_size=1",
                    "https://api.incident.io/v2/schedules",
                    "https://api.incident.io/v2/schedule_entries?schedule_id=S1",
                ],
                True,
            ),
            # No parent row to bind, so the child scope can't be probed and the parent probe decides.
            (
                "catalog_entries",
                "catalog_types",
                [],
                403,
                ["https://api.incident.io/v3/catalog_types", "https://api.incident.io/v3/catalog_types"],
                True,
            ),
        ],
    )
    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_fanout_schema_probes_parent_then_child(
        self, mock_session, schema_name, parent_key, parent_rows, child_status, expected_urls, expected_valid
    ):
        parent = mock.MagicMock(status_code=200)
        parent.json.return_value = {parent_key: parent_rows}
        mock_session.return_value.get.side_effect = [parent, parent, mock.MagicMock(status_code=child_status)]

        is_valid, error = validate_credentials("key", schema_name=schema_name)

        assert [call.args[0] for call in mock_session.return_value.get.call_args_list] == expected_urls
        assert is_valid is expected_valid
        if not expected_valid:
            assert error is not None and schema_name in error

    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_sends_bearer_auth_header(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("secret-key")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer secret-key"

    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_swallows_network_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("key")

        assert is_valid is False
        assert error is not None


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_pagination_meta_after(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, params = _source(
            session,
            [
                _response(_page_body("incidents", [{"id": "01A"}, {"id": "01B"}], "01B")),
                _response(_page_body("incidents", [{"id": "01C"}], None)),
            ],
            "incidents",
            manager,
        )

        assert [r["id"] for r in rows] == ["01A", "01B", "01C"]
        assert "after" not in params[0]
        assert params[1]["after"] == "01B"
        # State is saved only while a next page exists, after the batch was yielded.
        manager.save_state.assert_called_once()
        assert "after=01B" in manager.save_state.call_args.args[0].next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_filter_and_sort(self, MockSession):
        session = MockSession.return_value
        _, params = _source(
            session,
            [_response(_page_body("incidents", [], None))],
            "incidents",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, 12, 30, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert params[0]["updated_at[gte]"] == "2024-05-01"
        assert params[0]["sort_by"] == "created_at_oldest_first"
        assert params[0]["page_size"] == 250

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_ignores_incremental_value(self, MockSession):
        session = MockSession.return_value
        _, params = _source(
            session,
            [_response(_page_body("incidents", [], None))],
            "incidents",
            _make_manager(),
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert not any("gte" in key for key in params[0])

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state_and_preserves_filters(self, MockSession):
        session = MockSession.return_value
        resume_url = _build_url(
            "/v2/incidents",
            {"page_size": 250, "sort_by": "created_at_oldest_first", "updated_at[gte]": "2024-05-01", "after": "01B"},
        )
        manager = _make_manager(IncidentIoResumeConfig(next_url=resume_url))
        _, params = _source(
            session,
            [
                _response(_page_body("incidents", [{"id": "01C"}], "01C")),
                _response(_page_body("incidents", [], None)),
            ],
            "incidents",
            manager,
        )

        # First request replays the saved cursor and keeps the original chain's filter.
        assert params[0]["after"] == "01B"
        assert params[0]["updated_at[gte]"] == "2024-05-01"
        # The next page swaps in the new cursor but keeps the filter.
        assert params[1]["after"] == "01C"
        assert params[1]["updated_at[gte]"] == "2024-05-01"
        assert "after=01C" in manager.save_state.call_args.args[0].next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_once(self, MockSession):
        session = MockSession.return_value
        # Body carries an `after`, but a non-paginated endpoint must still fetch exactly once.
        body = {"severities": [{"id": "01A"}], "pagination_meta": {"after": "01A"}}
        manager = _make_manager()
        rows, _ = _source(session, [_response(body)], "severities", manager)

        assert session.send.call_count == 1
        assert [r["id"] for r in rows] == ["01A"]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_alert_sources_drop_secret_token(self, MockSession):
        session = MockSession.return_value
        body = {"alert_sources": [{"id": "01A", "name": "Datadog", "secret_token": "not-a-real-token"}]}
        rows, _ = _source(session, [_response(body)], "alert_sources", _make_manager())

        assert rows == [{"id": "01A", "name": "Datadog"}]
        # The raw body still carries the token, so it must never reach HTTP sample capture.
        assert MockSession.call_args.kwargs["capture"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_no_rows(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, _ = _source(session, [_response(_page_body("alerts", [], None))], "alerts", manager)

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession):
        session = MockSession.return_value
        rows, _ = _source(session, [_response({"pagination_meta": {"after": None}})], "incidents", _make_manager())

        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_429_honoring_retry_after(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, _ = _source(
            session,
            [
                _response({}, status_code=429, retry_after="0"),
                _response(_page_body("incidents", [{"id": "01A"}], None)),
            ],
            "incidents",
            manager,
        )

        assert session.send.call_count == 2
        assert [r["id"] for r in rows] == ["01A"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_5xx(self, MockSession):
        session = MockSession.return_value
        manager = _make_manager()
        rows, _ = _source(
            session,
            [
                _response({}, status_code=500, retry_after="0"),
                _response(_page_body("incidents", [{"id": "01A"}], None)),
            ],
            "incidents",
            manager,
        )

        assert session.send.call_count == 2
        assert [r["id"] for r in rows] == ["01A"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_client_error(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=404)])

        response = incident_io_source(
            "key", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        with pytest.raises(Exception):
            [row for page in cast("Iterable[Any]", response.items()) for row in page]


class TestFanout:
    @pytest.mark.parametrize(
        "endpoint, parent_key, child_path, parent_id_param, parent_params",
        [
            ("catalog_entries", "catalog_types", "/v3/catalog_entries", "catalog_type_id", {}),
            ("custom_field_options", "custom_fields", "/v1/custom_field_options", "custom_field_id", {}),
            (
                "status_page_incidents",
                "status_pages",
                "/v2/status_page_incidents",
                "status_page_id",
                {"page_size": 250},
            ),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fetches_child_pages_per_parent(
        self, MockSession, endpoint, parent_key, child_path, parent_id_param, parent_params
    ):
        session = MockSession.return_value
        manager = _make_manager()
        urls: list[str] = []
        params = _wire(
            session,
            [
                _response({parent_key: [{"id": "P1"}, {"id": "P2"}]}),
                _response(_page_body(endpoint, [{"id": "C1", parent_id_param: "P1"}], "C1")),
                _response(_page_body(endpoint, [{"id": "C2", parent_id_param: "P1"}], None)),
                _response(_page_body(endpoint, [{"id": "C3", parent_id_param: "P2"}], None)),
            ],
            urls,
        )

        response = incident_io_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
        rows = [row for page in cast("Iterable[Any]", response.items()) for row in page]

        assert [(r["id"], r[parent_id_param]) for r in rows] == [("C1", "P1"), ("C2", "P1"), ("C3", "P2")]
        assert params[0] == parent_params
        assert [urlsplit(url).path for url in urls[1:]] == [child_path] * 3
        assert [parse_qs(urlsplit(url).query)[parent_id_param] for url in urls[1:]] == [["P1"], ["P1"], ["P2"]]
        assert [p.get("page_size") for p in params[1:]] == [250, 250, 250]
        assert [p.get("after") for p in params[1:]] == [None, "C1", None]
        assert manager.save_state.call_args.args[0].fanout_state is not None

    @time_machine.travel(datetime(2026, 3, 1, 12, 0, tzinfo=UTC), tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_schedule_entries_page_through_window_per_schedule(self, MockSession):
        session = MockSession.return_value
        urls: list[str] = []

        def _entries_body(final: list[dict[str, Any]], after: str | None) -> dict[str, Any]:
            body: dict[str, Any] = {
                "schedule_entries": {"final": final, "scheduled": [{"fingerprint": "raw"}], "overrides": []}
            }
            if after is not None:
                body["pagination_meta"] = {"after": after, "after_url": "https://api.incident.io/next"}
            return body

        manager = _make_manager()
        params = _wire(
            session,
            [
                _response({"schedules": [{"id": "S1"}, {"id": "S2"}], "pagination_meta": {"page_size": 250}}),
                _response(_entries_body([{"fingerprint": "F1", "start_at": "2026-01-01T00:00:00Z"}], "opaque-1")),
                _response(_entries_body([{"fingerprint": "F2", "start_at": "2026-01-08T00:00:00Z"}], None)),
                _response(_entries_body([{"fingerprint": "F3", "start_at": "2026-01-02T00:00:00Z"}], None)),
            ],
            urls,
        )

        response = incident_io_source(
            "key", "schedule_entries", team_id=1, job_id="j", resumable_source_manager=manager
        )
        rows = [row for page in cast("Iterable[Any]", response.items()) for row in page]

        assert [(r["schedule_id"], r["fingerprint"]) for r in rows] == [("S1", "F1"), ("S1", "F2"), ("S2", "F3")]
        assert params[0] == {"page_size": 250}
        assert [parse_qs(urlsplit(url).query)["schedule_id"] for url in urls[1:]] == [["S1"], ["S1"], ["S2"]]
        # The cursor replaces the window start; the window end stays fixed across pages.
        assert [p.get("entry_window_start") for p in params[1:]] == [
            "2025-03-01T12:00:00Z",
            "opaque-1",
            "2025-03-01T12:00:00Z",
        ]
        assert {p.get("entry_window_end") for p in params[1:]} == {"2026-03-31T12:00:00Z"}
        assert all("page_size" not in p for p in params[1:])
        assert manager.save_state.call_args.args[0].window_params == {
            "entry_window_start": "2025-03-01T12:00:00Z",
            "entry_window_end": "2026-03-31T12:00:00Z",
        }

    @time_machine.travel(datetime(2026, 3, 2, 12, 0, tzinfo=UTC), tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_schedule_entries_resume_keeps_original_window(self, MockSession):
        session = MockSession.return_value
        window = {"entry_window_start": "2025-03-01T12:00:00Z", "entry_window_end": "2026-03-31T12:00:00Z"}
        manager = _make_manager(
            IncidentIoResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/v2/schedule_entries?schedule_id=S1",
                    "child_state": {"cursor": "opaque-1"},
                },
                window_params=window,
            )
        )
        params = _wire(
            session,
            [
                _response({"schedules": [{"id": "S1"}], "pagination_meta": {"page_size": 250}}),
                _response({"schedule_entries": {"final": [{"fingerprint": "F1"}]}}),
            ],
        )

        response = incident_io_source(
            "key", "schedule_entries", team_id=1, job_id="j", resumable_source_manager=manager
        )
        list(cast("Iterable[Any]", response.items()))

        assert params[1]["entry_window_start"] == "opaque-1"
        assert params[1]["entry_window_end"] == "2026-03-31T12:00:00Z"


class TestIncidentIoSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        config = INCIDENT_IO_ENDPOINTS[endpoint]
        response = incident_io_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(INCIDENT_IO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"created_at", "start_at", "published_at"}

    @pytest.mark.parametrize("config", list(INCIDENT_IO_ENDPOINTS.values()))
    def test_endpoint_paths_are_versioned(self, config):
        assert config.path.startswith(("/v1/", "/v2/", "/v3/"))
