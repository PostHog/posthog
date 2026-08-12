import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace import dynatrace as dt
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.dynatrace import (
    DynatraceHostNotAllowedError,
    DynatraceResumeConfig,
    _build_url,
    _format_from_value,
    _validated_hostname,
    check_endpoint_permissions,
    dynatrace_source,
    normalize_environment_url,
    validate_credentials,
)

BASE_URL = "https://abc12345.live.dynatrace.com"

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


class TestNormalizeEnvironmentUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://abc12345.live.dynatrace.com", "https://abc12345.live.dynatrace.com"),
            ("https://abc12345.live.dynatrace.com/", "https://abc12345.live.dynatrace.com"),
            ("abc12345.live.dynatrace.com", "https://abc12345.live.dynatrace.com"),
            (" https://abc12345.live.dynatrace.com ", "https://abc12345.live.dynatrace.com"),
            # A pasted API path must not double up when endpoint paths are appended.
            ("https://abc12345.live.dynatrace.com/api/v2", "https://abc12345.live.dynatrace.com"),
            ("https://abc12345.live.dynatrace.com/api", "https://abc12345.live.dynatrace.com"),
            # Managed environments carry a path prefix that must be preserved.
            ("https://dynatrace.example.com/e/abc-123", "https://dynatrace.example.com/e/abc-123"),
            ("https://dynatrace.example.com/e/abc-123/api/v2", "https://dynatrace.example.com/e/abc-123"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert normalize_environment_url(raw) == expected


class TestValidatedHostname:
    def test_accepts_clean_https_url(self) -> None:
        assert _validated_hostname(BASE_URL) == "abc12345.live.dynatrace.com"

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1\\@example.com",  # backslash userinfo smuggling
            "https://127.0.0.1%5C@example.com",  # percent-encoded backslash
            "https://user@example.com",  # userinfo
            "ftp://example.com",  # non-http scheme
            "https://exa mple.com",  # invalid hostname characters
        ],
    )
    def test_rejects_ambiguous_urls(self, url: str) -> None:
        assert _validated_hostname(url) is None

    def test_rejects_plain_http_on_cloud(self) -> None:
        with mock.patch.object(dt, "is_cloud", return_value=True):
            assert _validated_hostname("http://dynatrace.internal.example.com") is None

    def test_allows_plain_http_when_self_hosted(self) -> None:
        with mock.patch.object(dt, "is_cloud", return_value=False):
            assert _validated_hostname("http://dynatrace.internal.example.com") == "dynatrace.internal.example.com"


class TestFormatFromValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1735689600000, "1735689600000"),  # epoch-ms watermark passes through
            (datetime(2025, 1, 1, tzinfo=UTC), "1735689600000"),
            (datetime(2025, 1, 1), "1735689600000"),  # naive datetimes treated as UTC
            ("now-30d", "now-30d"),  # relative seeds pass through
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_from_value(value) == expected


def _response(body: dict[str, Any], *, status: int = 200, location: str | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = f"{BASE_URL}/api/v2/problems"
    if location:
        resp.headers["Location"] = location
    return resp


def _make_manager(resume_key: str | None = None) -> tuple[mock.MagicMock, list[str]]:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_key is not None
    manager.load_state.return_value = DynatraceResumeConfig(next_page_key=resume_key) if resume_key else None
    saved: list[str] = []
    manager.save_state.side_effect = lambda state: saved.append(state.next_page_key)
    return manager, saved


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT PREPARE TIME.

    ``request.params`` is one dict mutated in place across pages (the paginator swaps in the cursor),
    so snapshot a copy when each request is prepared rather than reading the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = f"{BASE_URL}/api/v2/problems"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Any:
    return dynatrace_source(
        environment_url=BASE_URL,
        api_token="token",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestFirstPageParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_run_uses_watermark(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"problems": [], "nextPageKey": None})])
        manager, _ = _make_manager()
        _rows(
            _source(
                "problems", manager, should_use_incremental_field=True, db_incremental_field_last_value=1735689600000
            )
        )
        assert params[0]["from"] == "1735689600000"
        assert params[0]["pageSize"] == "500"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_sync_seeds_lookback(self, MockSession: mock.MagicMock) -> None:
        # Without an explicit `from`, Dynatrace only returns the last 2 hours of problems.
        session = MockSession.return_value
        params = _wire(session, [_response({"problems": [], "nextPageKey": None})])
        manager, _ = _make_manager()
        _rows(_source("problems", manager))
        assert params[0]["from"] == "now-365d"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_entity_endpoint_sends_selector_and_fields(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"entities": [], "nextPageKey": None})])
        manager, _ = _make_manager()
        _rows(_source("hosts", manager))
        assert params[0]["entitySelector"] == 'type("HOST")'
        assert params[0]["from"] == "now-30d"
        assert params[0]["fields"].startswith("+firstSeenTms")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_time_filtered_endpoint_never_sends_from(self, MockSession: mock.MagicMock) -> None:
        # `metrics` has no timeframe filter; a stray watermark must not leak into the request.
        session = MockSession.return_value
        params = _wire(session, [_response({"metrics": [], "nextPageKey": None})])
        manager, _ = _make_manager()
        _rows(
            _source(
                "metrics", manager, should_use_incremental_field=True, db_incremental_field_last_value=1735689600000
            )
        )
        assert "from" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_slos_request_evaluation(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"slo": [], "nextPageKey": None})])
        manager, _ = _make_manager()
        _rows(_source("slos", manager))
        # With evaluate=true the endpoint caps pageSize at 25.
        assert params[0]["evaluate"] == "true"
        assert params[0]["pageSize"] == "25"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_pagination_yields_and_saves_state_after_yield(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response({"problems": [{"problemId": "P-1"}], "nextPageKey": "key-2"}),
                _response({"problems": [{"problemId": "P-2"}], "nextPageKey": None}),
            ],
        )
        manager, saved = _make_manager()
        rows = _rows(_source("problems", manager))

        assert rows == [{"problemId": "P-1"}, {"problemId": "P-2"}]
        assert saved == ["key-2"]
        # Follow-up request carries only the cursor — Dynatrace rejects mixed params.
        assert params[1] == {"nextPageKey": "key-2"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"problems": [{"problemId": "P-9"}], "nextPageKey": None})])
        manager, _ = _make_manager(resume_key="resume-key")
        rows = _rows(_source("problems", manager))

        assert rows == [{"problemId": "P-9"}]
        # The saved cursor reseeds the first request and drops the first-page filters.
        assert params[0] == {"nextPageKey": "resume-key"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_cursor_still_advances(self, MockSession: mock.MagicMock) -> None:
        # A page can be empty while more pages remain; termination is the null nextPageKey,
        # not an empty batch.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"problems": [], "nextPageKey": "key-2"}),
                _response({"problems": [{"problemId": "P-1"}], "nextPageKey": None}),
            ],
        )
        manager, _ = _make_manager()
        rows = _rows(_source("problems", manager))

        assert rows == [{"problemId": "P-1"}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession: mock.MagicMock) -> None:
        # A body without the data key is treated as an empty page (previous behavior), not an error.
        session = MockSession.return_value
        _wire(session, [_response({"unexpected": [], "nextPageKey": None})])
        manager, _ = _make_manager()
        assert _rows(_source("problems", manager)) == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_is_refused(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=302, location="https://evil.example.com")])
        manager, _ = _make_manager()
        # Redirects are disabled so the Authorization header can't be bounced off the validated host.
        with pytest.raises(ValueError):
            _rows(_source("problems", manager))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unsafe_host_is_refused_before_any_request(self, MockSession: mock.MagicMock) -> None:
        with mock.patch.object(dt, "_is_host_safe", return_value=(False, "blocked")):
            manager, _ = _make_manager()
            with pytest.raises(DynatraceHostNotAllowedError):
                _rows(_source("problems", manager))
        # The host check runs before a session is ever built.
        MockSession.assert_not_called()


class TestDynatraceSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pk", "expected_sort_mode"),
        [
            ("problems", "problemId", "desc"),
            ("events", "eventId", "desc"),
            ("audit_logs", "logId", "desc"),
            ("security_problems", "securityProblemId", "asc"),
            ("hosts", "entityId", "asc"),
            ("metrics", "metricId", "asc"),
            ("slos", "id", "asc"),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: str, expected_sort_mode: str) -> None:
        response = _source(endpoint, mock.MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.sort_mode == expected_sort_mode


class TestValidateCredentials:
    def _validate(self, status_code: int, schema_name: str | None = None) -> tuple[bool, str | None]:
        response = mock.MagicMock()
        response.status_code = status_code
        with mock.patch.object(dt, "make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = response
            return validate_credentials(BASE_URL, "token", team_id=None, schema_name=schema_name)

    @pytest.mark.parametrize(
        ("status_code", "schema_name", "expected_valid"),
        [
            (200, None, True),
            (401, None, False),
            # 403 at source-create means the token is genuine but lacks the probed scope —
            # users may legitimately only grant scopes for the tables they sync.
            (403, None, True),
            (403, "problems", False),
            (200, "hosts", True),
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status_code: int, schema_name: str | None, expected_valid: bool) -> None:
        is_valid, error = self._validate(status_code, schema_name)
        assert is_valid is expected_valid
        if not expected_valid:
            assert error is not None

    def test_malformed_url_fails_without_network(self) -> None:
        with mock.patch.object(dt, "make_tracked_session") as mock_session:
            is_valid, error = validate_credentials("ftp://example.com", "token")
        assert is_valid is False
        assert error is not None
        mock_session.assert_not_called()

    def test_request_exception_is_caught(self) -> None:
        with mock.patch.object(dt, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            is_valid, error = validate_credentials(BASE_URL, "token")
        assert is_valid is False
        assert error is not None


class TestCheckEndpointPermissions:
    def test_403_reports_missing_scope_and_shares_probe_across_entity_tables(self) -> None:
        def fake_get(url: str, timeout: Any = None) -> Any:
            response = mock.MagicMock()
            response.status_code = 403 if "entities" in url else 200
            return response

        with (
            mock.patch.object(dt, "make_tracked_session") as mock_session,
            mock.patch.object(dt, "_is_host_safe", return_value=(True, None)),
        ):
            mock_session.return_value.get.side_effect = fake_get
            results = check_endpoint_permissions(
                BASE_URL, "token", ["problems", "hosts", "services", "applications", "process_groups"], team_id=1
            )
            call_count = mock_session.return_value.get.call_count

        assert results["problems"] is None
        for endpoint in ("hosts", "services", "applications", "process_groups"):
            reason = results[endpoint]
            assert reason is not None
            assert "entities.read" in reason
        # The four entity tables share the entities.read scope, so one probe covers them all.
        assert call_count == 2

    def test_network_blip_is_not_reported_as_missing_permission(self) -> None:
        with (
            mock.patch.object(dt, "make_tracked_session") as mock_session,
            mock.patch.object(dt, "_is_host_safe", return_value=(True, None)),
        ):
            mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            results = check_endpoint_permissions(BASE_URL, "token", ["problems"], team_id=1)

        assert results == {"problems": None}


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url(BASE_URL, "/api/v2/metrics", {}) == f"{BASE_URL}/api/v2/metrics"

    def test_managed_path_prefix_is_preserved(self) -> None:
        url = _build_url("https://dynatrace.example.com/e/abc-123", "/api/v2/problems", {"pageSize": "500"})
        assert url == "https://dynatrace.example.com/e/abc-123/api/v2/problems?pageSize=500"

    def test_query_is_url_encoded(self) -> None:
        url = _build_url(BASE_URL, "/api/v2/problems", {"entitySelector": 'type("HOST")'})
        parsed = urlparse(url)
        assert parse_qs(parsed.query) == {"entitySelector": ['type("HOST")']}
