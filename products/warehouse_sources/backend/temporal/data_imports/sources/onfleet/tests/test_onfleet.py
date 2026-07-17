import json
import base64
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.onfleet import (
    OnfleetResumeConfig,
    _to_epoch_ms,
    get_credentials_status,
    onfleet_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.settings import (
    ENDPOINTS,
    ONFLEET_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# get_credentials_status builds its own tracked session in the onfleet module.
ONFLEET_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.onfleet.make_tracked_session"
)


def _response(body: Any, status_code: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: OnfleetResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[requests.Response]) -> list[requests.PreparedRequest]:
    """Wire a mock session, preparing each request through a real Session so the Basic-auth header
    and per-page query string are built for real, and return the prepared requests in send order."""
    session.headers = {}
    real = requests.Session()
    prepared: list[requests.PreparedRequest] = []

    def _prepare(request: requests.Request) -> requests.PreparedRequest:
        p = real.prepare_request(request)
        prepared.append(p)
        return p

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return prepared


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _query(prepared: requests.PreparedRequest) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(prepared.url).query).items()}


def _run(endpoint: str, responses: list[requests.Response], manager: mock.MagicMock, **kwargs):
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        prepared = _wire(session, responses)
        rows = _rows(onfleet_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs))
    return rows, prepared, session


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (1700000000000, 1700000000000),
            (1700000000000.5, 1700000000000),
            ("1700000000000", 1700000000000),
            ("not-a-number", None),
            # datetime/date must convert to MILLISECONDS, not seconds — the crux of Onfleet's `from`.
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp()) * 1000),
        ],
    )
    def test_to_epoch_ms_values(self, value, expected):
        assert _to_epoch_ms(value) == expected


class TestBasicAuth:
    def test_api_key_is_username_with_empty_password(self):
        # Onfleet Basic auth: API key as username, empty password.
        _rows_, prepared, _session = _run("workers", [_response([{"id": "w1"}])], _make_manager())
        token = prepared[0].headers["Authorization"].removeprefix("Basic ")
        assert base64.b64decode(token).decode() == "key:"


class TestGetRowsPaginated:
    def test_paginates_via_last_id_and_stops_when_absent(self):
        manager = _make_manager()
        rows, prepared, _session = _run(
            "tasks",
            [
                _response({"lastId": "abc", "tasks": [{"id": "1"}, {"id": "2"}]}),
                _response({"tasks": [{"id": "3"}]}),  # no lastId -> final page
            ],
            manager,
        )

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        # Second request continues after the first page's lastId.
        assert _query(prepared[1])["lastId"] == "abc"
        # State saved once (only while a next cursor exists), after yielding the page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].last_id == "abc"

    def test_resumes_from_saved_cursor(self):
        manager = _make_manager(OnfleetResumeConfig(last_id="saved", from_ms=1234))
        _rows_, prepared, _session = _run("tasks", [_response({"tasks": [{"id": "9"}]})], manager)

        first = _query(prepared[0])
        assert first["lastId"] == "saved"
        assert first["from"] == "1234"

    def test_incremental_from_value_used_as_epoch_ms(self):
        _rows_, prepared, _session = _run(
            "tasks",
            [_response({"tasks": [{"id": "1"}]})],
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000000,
        )
        assert _query(prepared[0])["from"] == "1700000000000"

    def test_full_refresh_defaults_from_to_zero(self):
        _rows_, prepared, _session = _run("tasks", [_response({"tasks": [{"id": "1"}]})], _make_manager())
        assert _query(prepared[0])["from"] == "0"

    def test_empty_page_with_advancing_cursor_keeps_paginating(self):
        # A page can be empty yet still carry an advancing lastId; pagination must continue
        # (not terminate) so later, non-empty pages are not skipped.
        manager = _make_manager()
        rows, prepared, _session = _run(
            "tasks",
            [
                _response({"lastId": "p2", "tasks": []}),
                _response({"tasks": [{"id": "1"}]}),  # no lastId -> final page
            ],
            manager,
        )

        assert [row["id"] for row in rows] == ["1"]
        assert _query(prepared[1])["lastId"] == "p2"
        # No rows were yielded for the empty page, so no checkpoint was saved for it.
        manager.save_state.assert_not_called()

    def test_non_advancing_cursor_terminates(self):
        # A repeated lastId must not loop forever.
        manager = _make_manager()
        rows, prepared, session = _run(
            "tasks",
            [
                _response({"lastId": "x", "tasks": [{"id": "1"}]}),
                _response({"lastId": "x", "tasks": [{"id": "1"}]}),
            ],
            manager,
        )

        assert session.send.call_count == 2
        assert [row["id"] for row in rows] == ["1", "1"]


class TestGetRowsNonPaginated:
    def test_bare_array_endpoint_yields_once(self):
        manager = _make_manager()
        rows, _prepared, session = _run("workers", [_response([{"id": "w1"}, {"id": "w2"}])], manager)

        assert rows == [{"id": "w1"}, {"id": "w2"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    def test_single_object_endpoint_wraps_in_list(self):
        rows, _prepared, _session = _run("organization", [_response({"id": "org1", "name": "Acme"})], _make_manager())
        assert rows == [{"id": "org1", "name": "Acme"}]


class TestRetries:
    @mock.patch("tenacity.nap.time.sleep")
    def test_retryable_status_is_retried_then_succeeds(self, _mock_sleep):
        # Onfleet rate-limits (429) and returns 5xx on its internal timeout; the client must
        # retry those and then yield the successful page.
        manager = _make_manager()
        rows, _prepared, session = _run(
            "workers",
            [_response(None, status_code=429), _response([{"id": "w1"}])],
            manager,
        )
        assert rows == [{"id": "w1"}]
        assert session.send.call_count == 2


class TestGetCredentialsStatus:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(ONFLEET_SESSION_PATCH)
    def test_returns_status_code(self, mock_session, status_code):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert get_credentials_status("key") == status_code

    @mock.patch(ONFLEET_SESSION_PATCH)
    def test_returns_none_on_transport_error(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert get_credentials_status("key") is None


class TestOnfleetSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ONFLEET_ENDPOINTS[endpoint]
        response = onfleet_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        # Onfleet epoch-ms timestamps would misbucket under the datetime partitioner, so partitioning is off.
        assert response.partition_mode is None
        assert response.partition_keys is None
