import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.vantage import (
    VANTAGE_BASE_URL,
    VantageResumeConfig,
    VantageUntrustedURLError,
    validate_credentials,
    vantage_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the vantage module.
VANTAGE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.vantage.vantage.make_tracked_session"
)

NO_SLEEP = "tenacity.nap.time.sleep"


def _response(
    items: Optional[list[dict[str, Any]]],
    *,
    data_key: str = "cost_reports",
    next_url: Optional[str] = None,
    include_links: bool = True,
    status_code: int = 200,
) -> Response:
    body: dict[str, Any] = {}
    if items is not None:
        body[data_key] = items
    if include_links:
        body["links"] = {"next": next_url}
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = f"{VANTAGE_BASE_URL}/cost_reports"
    return resp


def _make_manager(resume_state: VantageResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session; capture each request's URL and params AT PREPARE (send) time.

    ``request.params``/``url`` are mutated in place across pages, so snapshot copies as each request
    is prepared. The prepared object mirrors ``Session.prepare_request`` — its ``url`` is what the
    host-pinning check inspects, so absolute next-page URLs must flow straight through.
    """
    session.headers = {}
    urls: list[str] = []
    params: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        urls.append(request.url)
        params.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return urls, params


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "cost_reports"):
    return vantage_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_links_next_and_terminates(self, MockSession) -> None:
        # Regression guard: not advancing the URL loops forever; not terminating on a null `next`
        # over-fetches. Rows must come back across every page, in order.
        session = MockSession.return_value
        p2 = f"{VANTAGE_BASE_URL}/cost_reports?page=2&limit=1000"
        urls, params = _wire(
            session,
            [
                _response([{"token": "a"}, {"token": "b"}], next_url=p2),
                _response([{"token": "c"}], next_url=None),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"token": "a"}, {"token": "b"}, {"token": "c"}]
        assert session.send.call_count == 2
        assert params[0]["limit"] == 1000
        assert urls[1] == p2  # second request follows the body's `links.next` verbatim

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_reads_endpoint_specific_data_key(self, MockSession) -> None:
        # The row array is nested under the endpoint's own key (e.g. "budgets"), never a hardcoded
        # "data" — reading the wrong key silently yields zero rows.
        session = MockSession.return_value
        _wire(session, [_response([{"token": "b1"}], data_key="budgets", next_url=None)])

        rows = _rows(_source(_make_manager(), endpoint="budgets"))
        assert rows == [{"token": "b1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_links_object_terminates(self, MockSession) -> None:
        # A last page may omit `links` entirely; the paginator must stop, not error.
        session = MockSession.return_value
        _wire(session, [_response([{"token": "a"}], include_links=False)])

        rows = _rows(_source(_make_manager()))
        assert rows == [{"token": "a"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_zero_rows(self, MockSession) -> None:
        # A 200 body without the endpoint's data key yields no rows (parity with `data.get(key, [])`),
        # rather than failing loud — Vantage is full-refresh so an empty response is a valid page.
        session = MockSession.return_value
        _wire(session, [_response(None, include_links=True, next_url=None)])

        rows = _rows(_source(_make_manager()))
        assert rows == []


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_starts_from_initial_url_with_limit(self, MockSession) -> None:
        session = MockSession.return_value
        urls, params = _wire(session, [_response([], next_url=None)])

        _rows(_source(_make_manager()))
        assert urls[0].endswith("/v2/cost_reports")
        assert params[0]["limit"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_url(self, MockSession) -> None:
        # Resuming starts from the saved next-page URL verbatim, not page 1.
        session = MockSession.return_value
        resume_url = f"{VANTAGE_BASE_URL}/cost_reports?page=5&limit=1000"
        urls, params = _wire(session, [_response([{"token": "z"}], next_url=None)])

        manager = _make_manager(VantageResumeConfig(next_url=resume_url))
        rows = _rows(_source(manager))

        assert rows == [{"token": "z"}]
        assert urls[0] == resume_url
        assert params[0] == {}  # the self-contained resume URL carries its own page/limit

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yield_only_while_pages_remain(self, MockSession) -> None:
        # State is persisted with the *pending* page's URL (so a crash re-yields the last page, not
        # skips it) and never on the final page (no `next` to resume from).
        session = MockSession.return_value
        p2 = f"{VANTAGE_BASE_URL}/cost_reports?page=2&limit=1000"
        _wire(
            session,
            [
                _response([{"token": "a"}, {"token": "b"}], next_url=p2),
                _response([{"token": "c"}, {"token": "d"}], next_url=None),
            ],
        )

        manager = _make_manager()
        _rows(_source(manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved  # persisted at least once
        assert all(s.next_url == p2 for s in saved)  # only ever the pending page, never the final one

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_makes_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"token": "a"}], next_url=None)])

        manager = _make_manager()
        _rows(_source(manager))
        manager.save_state.assert_not_called()


class TestUntrustedUrl:
    @parameterized.expand(
        [
            ("off_host", "https://evil.example.com/v2/cost_reports"),
            ("subdomain_lookalike", "https://api.vantage.sh.evil.example.com/v2/cost_reports"),
            ("plain_http", "http://api.vantage.sh/v2/cost_reports"),
            ("wrong_path_prefix", "https://api.vantage.sh/internal/cost_reports"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_untrusted_next_url_is_refused_without_sending_token(self, _name: str, bad_url: str, MockSession) -> None:
        # `links.next` is server-controlled; the bearer token must never leave Vantage's own HTTPS
        # host and `/v2/` path, so an off-host/non-HTTPS/wrong-path next link is refused before the
        # request that would carry the token to it goes out.
        session = MockSession.return_value
        _wire(session, [_response([{"token": "a"}], next_url=bad_url)])

        with pytest.raises(VantageUntrustedURLError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 1  # only the trusted first page was fetched

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_untrusted_resume_url_is_refused_before_any_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"token": "a"}], next_url=None)])

        manager = _make_manager(VantageResumeConfig(next_url="https://evil.example.com/v2/cost_reports"))
        with pytest.raises(VantageUntrustedURLError):
            _rows(_source(manager))
        session.send.assert_not_called()


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    @mock.patch(NO_SLEEP)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(None, include_links=False, status_code=status),
                _response([{"token": "a"}], next_url=None),
            ],
        )

        rows = _rows(_source(_make_manager()))
        assert rows == [{"token": "a"}]
        assert session.send.call_count == 2

    @mock.patch(NO_SLEEP)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_chunked_encoding_error_is_retried(self, MockSession, _sleep) -> None:
        # A connection dropped mid-stream surfaces from `send` as ChunkedEncodingError; reissue it.
        session = MockSession.return_value
        session.headers = {}
        good = _response([{"token": "a"}], next_url=None)
        urls: list[str] = []

        def _prepare(request: Any) -> mock.MagicMock:
            urls.append(request.url)
            prepared = mock.MagicMock()
            prepared.url = request.url
            return prepared

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [requests.exceptions.ChunkedEncodingError("Connection broken"), good]

        rows = _rows(_source(_make_manager()))
        assert rows == [{"token": "a"}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_is_raised_not_retried(self, MockSession) -> None:
        # A 4xx (other than 429) is a permanent client error — raise immediately so
        # get_non_retryable_errors can classify it, rather than burning retries.
        session = MockSession.return_value
        _wire(session, [_response(None, include_links=False, status_code=404)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(VANTAGE_SESSION_PATCH)
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("tok") is expected

    @mock.patch(VANTAGE_SESSION_PATCH)
    def test_network_error_is_invalid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("tok") is False

    @mock.patch(VANTAGE_SESSION_PATCH)
    def test_probes_cheap_ping_endpoint(self, mock_session) -> None:
        # Validation must not hit a Cost Report endpoint (5 req/5s cap) — `/ping` is the cheap probe.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("tok")
        assert mock_session.return_value.get.call_args.args[0] == f"{VANTAGE_BASE_URL}/ping"


class TestSourceResponse:
    @parameterized.expand([("cost_reports", "created_at"), ("workspaces", "created_at")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_datetime_partitioning_on_created_at(self, endpoint: str, partition_key: str, _MockSession) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.primary_keys == ["token"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]

    @parameterized.expand([("teams",), ("users",), ("report_notifications",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_partitioning_when_no_stable_created_at(self, endpoint: str, _MockSession) -> None:
        # These objects carry no creation timestamp; partitioning on a missing field would break sync.
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.primary_keys == ["token"]
