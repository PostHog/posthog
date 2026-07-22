import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.settings import ENDPOINTS, TEMPO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.tempo import (
    PAGE_SIZE,
    TEMPO_BASE_URL,
    TempoResumeConfig,
    _build_initial_params,
    _format_updated_from,
    check_access,
    tempo_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the tempo module.
TEMPO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.tempo.tempo.make_tracked_session"
)


def _response(
    results: list[dict[str, Any]], next_url: str | None, *, url: str = f"{TEMPO_BASE_URL}/accounts"
) -> Response:
    metadata: dict[str, Any] = {"count": len(results)}
    if next_url is not None:
        metadata["next"] = next_url
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"results": results, "metadata": metadata}).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = url
    return resp


def _raw_response(
    body: Any, *, status: int = 200, reason: str = "Error", url: str = f"{TEMPO_BASE_URL}/worklogs"
) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.reason = reason
    resp.url = url
    return resp


def _make_manager(resume_state: TempoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; return (param_snapshots, prepared_urls).

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy at prepare time.
    A real ``prepare_request`` produces a concrete URL so the client's host-pinning check runs against
    the actual next-page/resume URL, exactly as it would in production.
    """
    session.headers = {}
    real = requests.Session()
    param_snapshots: list[dict[str, Any]] = []
    prepared_urls: list[str] = []

    def _prepare(request: Any) -> Any:
        param_snapshots.append(dict(request.params or {}))
        prepared = real.prepare_request(request)
        prepared_urls.append(prepared.url or "")
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, prepared_urls


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "accounts", **kwargs: Any):
    return tempo_source("tempo-token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


class TestBuildInitialParams:
    def test_worklogs_incremental_with_watermark(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["worklogs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC),
            incremental_field="updatedAt",
        )
        assert params == {"limit": PAGE_SIZE, "orderBy": "UPDATED", "updatedFrom": "2026-03-01T12:30:45Z"}

    def test_worklogs_first_incremental_sync_has_no_updated_from(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["worklogs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updatedAt",
        )
        assert params == {"limit": PAGE_SIZE, "orderBy": "UPDATED"}

    def test_worklogs_full_refresh_keeps_order_by_matching_sort_mode(self) -> None:
        # sort_mode is declared "desc" statically, so the request must always order by UPDATED.
        params = _build_initial_params(
            TEMPO_ENDPOINTS["worklogs"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"limit": PAGE_SIZE, "orderBy": "UPDATED"}

    @parameterized.expand(
        [("wrong_field", "worklogs", "createdAt"), ("no_incremental_support", "accounts", "updatedAt")]
    )
    def test_rejects_unsupported_incremental_field(self, _name: str, endpoint: str, field: str) -> None:
        with pytest.raises(ValueError, match="does not support incremental field"):
            _build_initial_params(
                TEMPO_ENDPOINTS[endpoint],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
                incremental_field=field,
            )

    def test_plans_sends_required_date_window(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["plans"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["limit"] == PAGE_SIZE
        assert params["from"] == "2001-01-01"
        # Plans can extend into the future, so the window must end well past today.
        assert date.fromisoformat(params["to"]) > date.today()

    def test_unpaginated_endpoint_sends_no_params(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["holiday_schemes"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {}


class TestFormatUpdatedFrom:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
            (
                "non_utc_datetime",
                datetime(2026, 3, 1, 14, 30, 45, tzinfo=timezone(timedelta(hours=2))),
                "2026-03-01T12:30:45Z",
            ),
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45), "2026-03-01T12:30:45Z"),
            ("date", date(2026, 3, 1), "2026-03-01"),
            ("string_passthrough", "2026-03-01T12:30:45Z", "2026-03-01T12:30:45Z"),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: str) -> None:
        assert _format_updated_from(value) == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_without_next_yields_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}], next_url=None)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        # No `metadata.next`, so we stop without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_url_without_resending_params(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{TEMPO_BASE_URL}/accounts?limit={PAGE_SIZE}&offset={PAGE_SIZE}"
        params, urls = _wire(
            session,
            [_response([{"id": 1}], next_url=next_url), _response([{"id": 2}], next_url=None)],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": 1}, {"id": 2}]
        # The first request carries the built params; the next-page URL already embeds them, so the
        # second request sends no params and targets the returned link verbatim.
        assert params[0] == {"limit": PAGE_SIZE}
        assert params[1] == {}
        assert urls[1] == next_url
        # State saved once, after the first page, carrying the URL that fetches the second page.
        manager.save_state.assert_called_once_with(TempoResumeConfig(next_url=next_url))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{TEMPO_BASE_URL}/accounts?limit={PAGE_SIZE}&offset={PAGE_SIZE}"
        params, urls = _wire(session, [_response([{"id": 5}], next_url=None)])

        manager = _make_manager(TempoResumeConfig(next_url=next_url))
        rows = _rows(_source(manager))

        # The initial page must never be fetched on resume — one request, seeded with the saved URL.
        assert rows == [{"id": 5}]
        assert session.send.call_count == 1
        assert urls[0] == next_url
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_url=None)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_carries_limit(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response([{"id": 1}], next_url=None)])

        _rows(_source(_make_manager()))
        assert params[0] == {"limit": PAGE_SIZE}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_api_token_not_placed_in_session_headers(self, MockSession) -> None:
        # The token rides in the framework Bearer auth (redacted from logs/errors), never a hand-set
        # header — only the non-secret Accept header is on the session.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], next_url=None)])

        _rows(_source(_make_manager()))
        assert "tempo-token" not in json.dumps(session.headers)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_url_is_rejected(self, MockSession) -> None:
        # metadata.next is server-controlled and the session carries the Bearer token, so a next URL
        # off the Tempo API host must fail (host-pinning) instead of being followed.
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], next_url="https://evil.example.com/4/accounts")])

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_resume_state_is_rejected(self, MockSession) -> None:
        # Resume state is persisted outside the process; a poisoned next_url must not receive the
        # credentialed request.
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(TempoResumeConfig(next_url="https://evil.example.com/4/accounts?offset=100"))
        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source(manager))
        session.send.assert_not_called()


class TestTransportErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_recover(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        transient = _raw_response({"results": []}, status=status)
        _wire(session, [transient, _response([{"id": 1}], next_url=None)])

        rows = _rows(_source(_make_manager()))
        assert rows == [{"id": 1}]
        # A 429/5xx is retried rather than surfacing — the retry lands on the recovered page.
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_persistent_retryable_status_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response({"results": []}, status=500) for _ in range(5)])

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager()))

    @parameterized.expand(
        [("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden"), ("not_found", 404, "Not Found")]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_http_error(self, _name: str, status: int, reason: str, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response({}, status=status, reason=reason)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_http_error_message_keeps_stable_prefix(self, MockSession) -> None:
        # The message becomes the schema's latest_error and must keep the prefix
        # get_non_retryable_errors() matches on. No secret rides in the URL (the token is a header).
        session = MockSession.return_value
        _wire(
            session,
            [
                _raw_response(
                    {},
                    status=401,
                    reason="Unauthorized",
                    url=f"{TEMPO_BASE_URL}/worklogs?limit=100&updatedFrom=2026-03-01",
                )
            ],
        )

        with pytest.raises(requests.HTTPError) as exc:
            _rows(_source(_make_manager(), "worklogs"))
        assert "401 Client Error: Unauthorized for url: https://api.tempo.io" in str(exc.value)

    @parameterized.expand([("non_dict_body", [{"id": 1}]), ("missing_results_key", {"metadata": {"count": 0}})])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_is_retried_then_recovers(self, _name: str, bad_body: Any, MockSession, _sleep) -> None:
        # A 200 whose body isn't the expected {"results": [...]} envelope is a transient bad shape —
        # retry, don't fail loud.
        session = MockSession.return_value
        _wire(session, [_raw_response(bad_body), _response([{"id": 1}], next_url=None)])

        rows = _rows(_source(_make_manager()))
        assert rows == [{"id": 1}]
        assert session.send.call_count == 2


class TestTempoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint)
        assert response.name == endpoint
        assert response.primary_keys == TEMPO_ENDPOINTS[endpoint].primary_keys

    def test_worklogs_response_is_desc_and_partitioned_on_created_at(self) -> None:
        response = _source(_make_manager(), "worklogs")
        assert response.primary_keys == ["tempoWorklogId"]
        # orderBy=UPDATED returns newest-update-first; declaring desc defers the watermark commit
        # to sync completion, so a mid-sync crash can't skip rows.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    def test_full_refresh_endpoints_are_asc_and_unpartitioned(self) -> None:
        response = _source(_make_manager(), "accounts")
        assert response.sort_mode == "asc"
        assert response.partition_mode is None


class TestCheckAccess:
    @parameterized.expand(
        [
            ("ok", 200, 200, None),
            ("unauthorized", 401, 401, None),
            ("forbidden", 403, 403, None),
            ("server_error", 500, 500, "Tempo returned HTTP 500"),
        ]
    )
    @mock.patch(TEMPO_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_status: int, expected_message: str | None, mock_session: mock.MagicMock
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status
        mock_session.return_value.get.return_value = response
        assert check_access("tempo-token") == (expected_status, expected_message)

    @mock.patch(TEMPO_SESSION_PATCH)
    def test_connection_error_maps_to_zero(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert check_access("tempo-token") == (0, "Could not connect to Tempo")

    @parameterized.expand(
        [
            ("ok_no_endpoint", 200, None, (True, None)),
            ("unauthorized", 401, None, (False, "Invalid Tempo API token")),
            # A 403 at source-create still proves the token is genuine — Tempo tokens are scoped.
            ("forbidden_at_create", 403, None, (True, None)),
            (
                "forbidden_for_schema",
                403,
                "teams",
                (False, "Your Tempo API token is missing the view scope for 'teams'"),
            ),
            ("server_error", 500, None, (False, "Tempo returned HTTP 500")),
        ]
    )
    @mock.patch(TEMPO_SESSION_PATCH)
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        endpoint: str | None,
        expected: tuple[bool, str | None],
        mock_session: mock.MagicMock,
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status
        mock_session.return_value.get.return_value = response
        assert validate_credentials("tempo-token", endpoint=endpoint) == expected
