from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace import dynatrace as dt
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.dynatrace import (
    DynatraceHostNotAllowedError,
    DynatraceResumeConfig,
    _build_first_page_params,
    _build_url,
    _format_from_value,
    _next_page_url,
    _validated_hostname,
    check_endpoint_permissions,
    dynatrace_source,
    normalize_environment_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.settings import DYNATRACE_ENDPOINTS

BASE_URL = "https://abc12345.live.dynatrace.com"


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


class TestBuildFirstPageParams:
    def test_incremental_run_uses_watermark(self) -> None:
        params = _build_first_page_params(
            DYNATRACE_ENDPOINTS["problems"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1735689600000,
        )
        assert params["from"] == "1735689600000"
        assert params["pageSize"] == "500"

    def test_first_sync_seeds_lookback(self) -> None:
        # Without an explicit `from`, Dynatrace only returns the last 2 hours of problems.
        params = _build_first_page_params(
            DYNATRACE_ENDPOINTS["problems"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params["from"] == "now-365d"

    def test_full_refresh_ignores_watermark(self) -> None:
        params = _build_first_page_params(
            DYNATRACE_ENDPOINTS["problems"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1735689600000,
        )
        assert params["from"] == "now-365d"

    def test_entity_endpoint_sends_selector_and_fields(self) -> None:
        params = _build_first_page_params(
            DYNATRACE_ENDPOINTS["hosts"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert params["entitySelector"] == 'type("HOST")'
        assert params["from"] == "now-30d"
        assert params["fields"].startswith("+firstSeenTms")

    def test_non_time_filtered_endpoint_never_sends_from(self) -> None:
        # `metrics` has no timeframe filter; a stray watermark must not leak into the request.
        params = _build_first_page_params(
            DYNATRACE_ENDPOINTS["metrics"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1735689600000,
        )
        assert "from" not in params

    def test_slos_request_evaluation(self) -> None:
        params = _build_first_page_params(
            DYNATRACE_ENDPOINTS["slos"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        # With evaluate=true the endpoint caps pageSize at 25.
        assert params["evaluate"] == "true"
        assert params["pageSize"] == "25"


class TestNextPageUrl:
    def test_carries_only_next_page_key(self) -> None:
        # Dynatrace rejects follow-up pages that mix nextPageKey with any other query param.
        url = _next_page_url(BASE_URL, DYNATRACE_ENDPOINTS["problems"], "AQAAABQBAAAABQ==")
        parsed = urlparse(url)
        assert parsed.path == "/api/v2/problems"
        assert parse_qs(parsed.query) == {"nextPageKey": ["AQAAABQBAAAABQ=="]}

    def test_key_is_url_encoded(self) -> None:
        url = _next_page_url(BASE_URL, DYNATRACE_ENDPOINTS["problems"], "a+b/c==")
        assert "nextPageKey=a%2Bb%2Fc%3D%3D" in url


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
            assert results[endpoint] is not None
            assert "entities.read" in results[endpoint]
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
        response = dynatrace_source(
            environment_url=BASE_URL,
            api_token="token",
            endpoint=endpoint,
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.sort_mode == expected_sort_mode


class TestGetRows:
    def _run(
        self,
        pages: list[Any],
        can_resume: bool = False,
        resume_key: str | None = None,
        endpoint: str = "problems",
    ) -> tuple[list[Any], list[str], list[str]]:
        manager = mock.MagicMock()
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = DynatraceResumeConfig(next_page_key=resume_key) if resume_key else None
        saved: list[str] = []
        manager.save_state.side_effect = lambda state: saved.append(state.next_page_key)

        fetched_urls: list[str] = []

        def fake_get(url: str, timeout: Any = None) -> Any:
            fetched_urls.append(url)
            response = mock.MagicMock()
            response.status_code = 200
            response.ok = True
            response.json.return_value = pages[len(fetched_urls) - 1]
            return response

        with mock.patch.object(dt, "make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = fake_get
            rows = list(
                dt.get_rows(
                    environment_url=BASE_URL,
                    api_token="token",
                    endpoint=endpoint,
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )
        return rows, saved, fetched_urls

    def test_cursor_pagination_yields_and_saves_state_after_yield(self) -> None:
        pages = [
            {"problems": [{"problemId": "P-1"}], "nextPageKey": "key-2"},
            {"problems": [{"problemId": "P-2"}], "nextPageKey": None},
        ]
        rows, saved, fetched = self._run(pages)

        assert rows == [[{"problemId": "P-1"}], [{"problemId": "P-2"}]]
        assert saved == ["key-2"]
        # Follow-up request carries only the cursor — Dynatrace rejects mixed params.
        assert parse_qs(urlparse(fetched[1]).query) == {"nextPageKey": ["key-2"]}

    def test_first_page_carries_filters(self) -> None:
        pages = [{"problems": [], "nextPageKey": None}]
        _rows, _saved, fetched = self._run(pages)
        query = parse_qs(urlparse(fetched[0]).query)
        assert query["pageSize"] == ["500"]
        assert query["from"] == ["now-365d"]

    def test_resumes_from_saved_cursor(self) -> None:
        pages = [{"problems": [{"problemId": "P-9"}], "nextPageKey": None}]
        _rows, _saved, fetched = self._run(pages, can_resume=True, resume_key="resume-key")
        assert parse_qs(urlparse(fetched[0]).query) == {"nextPageKey": ["resume-key"]}

    def test_empty_page_with_cursor_still_advances(self) -> None:
        # A page can be empty while more pages remain; termination is the null nextPageKey,
        # not an empty batch.
        pages = [
            {"problems": [], "nextPageKey": "key-2"},
            {"problems": [{"problemId": "P-1"}], "nextPageKey": None},
        ]
        rows, _saved, fetched = self._run(pages)
        assert rows == [[{"problemId": "P-1"}]]
        assert len(fetched) == 2

    def test_redirect_is_refused(self) -> None:
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        response = mock.MagicMock()
        response.status_code = 302

        with mock.patch.object(dt, "make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = response
            with pytest.raises(DynatraceHostNotAllowedError):
                list(
                    dt.get_rows(
                        environment_url=BASE_URL,
                        api_token="token",
                        endpoint="problems",
                        team_id=1,
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                    )
                )

    def test_unsafe_host_is_refused_before_any_request(self) -> None:
        with (
            mock.patch.object(dt, "_is_host_safe", return_value=(False, "blocked")),
            mock.patch.object(dt, "make_tracked_session") as mock_session,
        ):
            with pytest.raises(DynatraceHostNotAllowedError):
                list(
                    dt.get_rows(
                        environment_url=BASE_URL,
                        api_token="token",
                        endpoint="problems",
                        team_id=1,
                        logger=mock.MagicMock(),
                        resumable_source_manager=mock.MagicMock(),
                    )
                )
        mock_session.assert_not_called()


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url(BASE_URL, "/api/v2/metrics", {}) == f"{BASE_URL}/api/v2/metrics"

    def test_managed_path_prefix_is_preserved(self) -> None:
        url = _build_url("https://dynatrace.example.com/e/abc-123", "/api/v2/problems", {"pageSize": "500"})
        assert url == "https://dynatrace.example.com/e/abc-123/api/v2/problems?pageSize=500"
