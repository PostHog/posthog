import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
import time_machine
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io import (
    IncidentIoResumeConfig,
    _build_params,
    _build_url,
    _format_filter_value,
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
    def test_incremental_filter_included_when_set(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], "updated_at", "2024-05-01")
        assert params["updated_at[gte]"] == "2024-05-01"


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
    def test_swallows_network_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("key")

        assert is_valid is False
        assert error is not None


class TestGetRows:
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
    def test_alert_sources_drop_secret_token(self, MockSession):
        session = MockSession.return_value
        body = {"alert_sources": [{"id": "01A", "name": "Datadog", "secret_token": "not-a-real-token"}]}
        rows, _ = _source(session, [_response(body)], "alert_sources", _make_manager())

        assert rows == [{"id": "01A", "name": "Datadog"}]
        # The raw body still carries the token, so it must never reach HTTP sample capture.
        assert MockSession.call_args.kwargs["capture"] is False

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
