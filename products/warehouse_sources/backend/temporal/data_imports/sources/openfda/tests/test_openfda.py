import json
from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.openfda import (
    OPENFDA_BASE_URL,
    PAGE_SIZE,
    OpenFDAResumeConfig,
    _auth_config,
    _build_params,
    _format_date_value,
    _make_basic_auth,
    openfda_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openfda.settings import OPENFDA_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the openfda module.
OPENFDA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.openfda.openfda.make_tracked_session"
)


def _response(
    status: int,
    *,
    results: list[dict[str, Any]] | None = None,
    body: Any = None,
    next_url: str | None = None,
    url: str = f"{OPENFDA_BASE_URL}/drug/enforcement.json",
    reason: str = "OK",
) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = reason
    if body is not None:
        resp._content = json.dumps(body).encode()
    elif results is not None:
        resp._content = json.dumps({"meta": {}, "results": results}).encode()
    else:
        resp._content = b"{}"
    if next_url:
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _make_manager(resume_state: OpenFDAResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so a copy is snapshotted when each
    request is prepared rather than inspected after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(manager: mock.MagicMock, endpoint: str = "drug_enforcement", **kwargs: Any) -> Any:
    return openfda_source(
        api_key=kwargs.pop("api_key", None),
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatDateValue:
    @parameterized.expand(
        [
            ("datetime", datetime(2020, 1, 2, 3, 4, 5), "20200102"),
            ("date", date(2020, 1, 2), "20200102"),
            ("yyyymmdd_string", "20200102", "20200102"),
            ("dashed_string", "2020-01-02", "20200102"),
        ]
    )
    def test_formats_to_yyyymmdd(self, _name: str, value: Any, expected: str) -> None:
        # The openFDA search date range only accepts YYYYMMDD; a mis-formatted watermark silently
        # matches nothing (404) and wedges the incremental sync.
        assert _format_date_value(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_bounds_by_date_and_sorts_ascending(self) -> None:
        params = _build_params(
            OPENFDA_ENDPOINTS["drug_enforcement"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2020, 1, 1),
            incremental_field=None,
        )
        # The server-side date filter must survive: without it every "incremental" sync re-scans the
        # whole dataset. Ascending sort keeps the pipeline watermark advancing monotonically.
        assert params["search"] == "report_date:[20200101 TO 99991231]"
        assert params["sort"] == "report_date:asc"
        assert params["limit"] == PAGE_SIZE

    def test_first_incremental_sync_has_no_date_filter(self) -> None:
        params = _build_params(
            OPENFDA_ENDPOINTS["drug_enforcement"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        # No watermark yet -> backfill the whole history, still ordered so the watermark is valid.
        assert "search" not in params
        assert params["sort"] == "report_date:asc"

    def test_user_selected_incremental_field_overrides_default(self) -> None:
        params = _build_params(
            OPENFDA_ENDPOINTS["drug_enforcement"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2020, 1, 1),
            incremental_field="recall_initiation_date",
        )
        # Honor the user's chosen cursor field instead of hardcoding the endpoint default.
        assert params["search"].startswith("recall_initiation_date:")
        assert params["sort"] == "recall_initiation_date:asc"

    def test_full_refresh_endpoint_omits_search_and_sort(self) -> None:
        params = _build_params(
            OPENFDA_ENDPOINTS["drug_ndc"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        # drug/ndc has no date cursor; it must page on the bare search_after cursor with no sort.
        assert "search" not in params
        assert "sort" not in params
        assert params["limit"] == PAGE_SIZE


class TestAuth:
    def test_key_becomes_basic_auth_username(self) -> None:
        auth = _make_basic_auth("secret")
        assert auth is not None
        assert auth.username == "secret"
        assert auth.password == ""

    def test_blank_key_sends_no_auth(self) -> None:
        # openFDA allows the unauthenticated tier; a missing key must not become auth at all.
        assert _make_basic_auth(None) is None
        assert _make_basic_auth("") is None
        assert _auth_config(None) is None
        assert _auth_config("") is None

    def test_auth_config_is_http_basic_with_key_as_username(self) -> None:
        # The framework auth injects the key as the Basic-auth username (empty password).
        assert _auth_config("secret") == {"type": "http_basic", "username": "secret", "password": ""}


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_link_cursor_across_pages(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response(200, results=[{"recall_number": "D-1"}], next_url="https://api.fda.gov/p2"),
                _response(200, results=[{"recall_number": "D-2"}]),
            ],
        )
        rows = _rows(_source(_make_manager()))
        assert rows == [{"recall_number": "D-1"}, {"recall_number": "D-2"}]
        # The first request carries the page size; the second follows the self-contained next link.
        assert params[0]["limit"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_last_page_terminates(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response(200, results=[{"recall_number": "D-9"}])])
        rows = _rows(_source(_make_manager()))
        assert rows == [{"recall_number": "D-9"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_cursor_after_yielding_each_page(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(200, results=[{"recall_number": "D-1"}], next_url="https://api.fda.gov/p2"),
                _response(200, results=[{"recall_number": "D-2"}]),
            ],
        )
        manager = _make_manager()
        _rows(_source(manager))
        # State is saved only while more pages remain, and only the next cursor — so a crash re-fetches
        # the just-yielded page (merge dedupes) rather than skipping it. The final page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == OpenFDAResumeConfig(next_url="https://api.fda.gov/p2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response(200, results=[{"recall_number": "D-2"}])])
        manager = _make_manager(OpenFDAResumeConfig(next_url="https://api.fda.gov/p2"))
        rows = _rows(_source(manager))
        # Resume must start at the saved cursor, not rebuild the initial URL (which would re-pull page
        # 1) — so the seeded next-page URL replaces the initial params entirely.
        assert rows == [{"recall_number": "D-2"}]
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_404_first_page_yields_nothing(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response(404, body={"error": {"code": "NOT_FOUND"}})])
        # openFDA returns 404 (not an empty results array) when nothing matches — expected at the tail
        # of an incremental run. Treating it as an error would fail every caught-up sync.
        rows = _rows(_source(_make_manager()))
        assert rows == []

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried(self, _name: str, status: int, MockSession: Any) -> None:
        RESTClient._send_request.retry.sleep = lambda *_: None  # type: ignore[attr-defined]
        session = MockSession.return_value
        _wire(session, [_response(status), _response(200, results=[{"recall_number": "D-1"}])])
        # 429 / 5xx are transient — the client backs off and retries rather than failing the sync.
        rows = _rows(_source(_make_manager()))
        assert rows == [{"recall_number": "D-1"}]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_error_raises(self, _name: str, status: int, reason: str, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response(status, reason=reason, body={"error": {}})])
        # 401/403 (bad or over-quota key) can never be fixed by retrying — they surface as an error.
        with pytest.raises(HTTPError):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_results_key_raises_loudly(self, MockSession: Any) -> None:
        session = MockSession.return_value
        _wire(session, [_response(200, body={"meta": {}})])
        # openFDA guarantees `results` on a 200; an unexpected shape must surface, not silently look
        # like an empty page.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))

    @parameterized.expand(
        [
            ("off_host", "https://evil.example.com/next"),
            ("insecure_scheme", "http://api.fda.gov/next"),
            ("subdomain_spoof", "https://api.fda.gov.evil.example.com/next"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_cursor_is_rejected(self, _name: str, next_url: str, MockSession: Any) -> None:
        # A poisoned `Link` header would send the API key (Basic auth) off-host or hit an internal
        # address. Following it must fail loudly, not be saved and requested.
        session = MockSession.return_value
        _wire(session, [_response(200, results=[], next_url=next_url)])
        with pytest.raises(ValueError):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_resume_cursor_is_rejected(self, MockSession: Any) -> None:
        # Poisoned resume state must not be followed — it would leak the API key off-host.
        session = MockSession.return_value
        _wire(session, [])
        manager = _make_manager(OpenFDAResumeConfig(next_url="https://evil.example.com/p2"))
        with pytest.raises(ValueError):
            _rows(_source(manager))


class TestOpenfdaSource:
    @parameterized.expand(
        [
            ("drug_enforcement", ["recall_number"], "report_date"),
            ("drug_ndc", ["product_id"], None),
            ("device_510k", ["k_number"], "decision_date"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_carries_endpoint_config(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None, MockSession: Any
    ) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            # Full-refresh endpoint: no sort requested, so arrival order is undefined.
            assert response.partition_mode is None
            assert response.sort_mode is None
        else:
            # Incremental endpoint: ascending sort must be declared so the pipeline checkpoints the
            # watermark correctly, and the stable date field partitions the table.
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.sort_mode == "asc"


class TestValidateCredentials:
    @mock.patch(OPENFDA_SESSION_PATCH)
    def test_success(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("key") is True

    @mock.patch(OPENFDA_SESSION_PATCH)
    def test_success_without_key(self, mock_session: Any) -> None:
        # openFDA allows the unauthenticated tier, so a blank key that reaches the API is still valid.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials(None) is True

    @mock.patch(OPENFDA_SESSION_PATCH)
    def test_failure(self, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("key") is False

    @mock.patch(OPENFDA_SESSION_PATCH)
    def test_swallows_exceptions(self, mock_session: Any) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False
