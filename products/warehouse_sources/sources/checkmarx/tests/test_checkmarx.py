from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx import (
    AUTH_ERROR_PREFIX,
    CheckmarxAuth,
    CheckmarxAuthError,
    CheckmarxResumeConfig,
    CheckmarxRetryableError,
    _build_incremental_value,
    _result_id,
    get_region_hosts,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.settings import (
    CHECKMARX_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.source import CheckmarxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkmarx import (
    CheckmarxSourceConfig,
)

TOKEN_PAYLOAD = {"access_token": "jwt-token", "expires_in": 1800}


def _response(status: int = 200, payload: Any = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = payload if payload is not None else {}
    response.text = text
    if status >= 400:
        response.raise_for_status.side_effect = HTTPError(
            f"{status} Client Error: Unauthorized for url: https://ast.checkmarx.net", response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


class FakeSession:
    """Routes POSTs to the token endpoint and GETs through a per-test handler."""

    def __init__(
        self,
        get_handler: Callable[[str, dict[str, Any]], MagicMock],
        token_response: MagicMock | None = None,
    ) -> None:
        self._get_handler = get_handler
        self._token_response = token_response or _response(payload=TOKEN_PAYLOAD)
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def post(self, url: str, data: dict[str, Any] | None = None, timeout: Any = None) -> MagicMock:
        self.post_calls.append((url, data or {}))
        return self._token_response

    def get(
        self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: Any = None
    ) -> MagicMock:
        self.get_calls.append((url, params or {}, headers or {}))
        return self._get_handler(url, params or {})


class TestCheckmarx:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(
            CheckmarxSource(), CheckmarxSourceConfig(tenant_name="my-tenant", region="us", api_key="key")
        )

    @staticmethod
    def _token() -> ScriptedResponse:
        return ScriptedResponse(json=TOKEN_PAYLOAD)

    # ---- auth ----

    def test_auth_quotes_tenant_name_in_realm_url(self) -> None:
        session = FakeSession(lambda url, params: _response())
        auth = CheckmarxAuth(session, "https://iam.checkmarx.net", " my/tenant ", "key")  # type: ignore[arg-type]

        auth.get_token()

        url, _data = session.post_calls[0]
        assert url == "https://iam.checkmarx.net/auth/realms/my%2Ftenant/protocol/openid-connect/token"

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_auth_error_statuses_raise_auth_error(self, status: int) -> None:
        token_response = _response(
            status=status, payload={"error": "invalid_grant", "error_description": "Token is not active"}
        )
        session = FakeSession(lambda url, params: _response(), token_response=token_response)
        auth = CheckmarxAuth(session, "https://iam.checkmarx.net", "my-tenant", "bad-key")  # type: ignore[arg-type]

        with pytest.raises(CheckmarxAuthError) as exc_info:
            auth.get_token()

        assert AUTH_ERROR_PREFIX in str(exc_info.value)
        assert "Token is not active" in str(exc_info.value)

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_auth_transient_statuses_raise_retryable_error(self, status: int) -> None:
        session = FakeSession(lambda url, params: _response(), token_response=_response(status=status))
        auth = CheckmarxAuth(session, "https://iam.checkmarx.net", "my-tenant", "key")  # type: ignore[arg-type]

        with pytest.raises(CheckmarxRetryableError):
            auth.get_token()

    # ---- region hosts ----

    def test_get_region_hosts_unknown_region(self) -> None:
        with pytest.raises(ValueError):
            get_region_hosts("mars")

    # ---- incremental value ----

    @pytest.mark.parametrize(
        ("endpoint", "value", "expected"),
        [
            ("scans", datetime(2026, 1, 15, 12, 30, tzinfo=UTC), "2026-01-15T12:30:00Z"),
            ("scans", date(2026, 1, 15), "2026-01-15T00:00:00Z"),
            # Fan-out endpoints subtract their 7-day safety lookback from the watermark.
            ("scan_results", datetime(2026, 1, 15, 12, 30, tzinfo=UTC), "2026-01-08T12:30:00Z"),
            ("scan_results_summary", date(2026, 1, 15), "2026-01-08T00:00:00Z"),
        ],
    )
    def test_build_incremental_value(self, endpoint: str, value: Any, expected: str) -> None:
        assert _build_incremental_value(CHECKMARX_ENDPOINTS[endpoint], True, value) == expected

    # ---- result id ----

    def test_result_id_hashes_rows_without_identifiers(self) -> None:
        item = {"type": "kics", "severity": "HIGH"}
        first = _result_id(item)
        second = _result_id(dict(item))

        assert first.startswith("kics:")
        assert first == second
        assert _result_id({"type": "kics", "severity": "LOW"}) != first

    # ---- top-level pagination ----

    def test_get_rows_paginates_until_short_page(self) -> None:
        page_size = CHECKMARX_ENDPOINTS["projects"].page_size
        full_page = [{"id": f"p{i}"} for i in range(page_size)]
        short_page = [{"id": "last"}]
        result = self._driver().run(
            "projects",
            [
                self._token(),
                ScriptedResponse(json={"projects": full_page, "totalCount": page_size + 1}),
                ScriptedResponse(json={"projects": short_page, "totalCount": page_size + 1}),
            ],
        )

        assert result.raised is None
        assert result.paths[1:] == ["/api/projects", "/api/projects"]
        assert [len(batch) for batch in result.items] == [page_size, 1]
        assert result.params("offset")[1:] == ["0", str(page_size)]
        # State saved after the yielded full page, pointing at the next offset.
        assert result.saved_states == [CheckmarxResumeConfig(offset=page_size)]

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "expects_from_date"),
        [(True, True), (False, False)],
    )
    def test_get_rows_scans_incremental_filter(
        self, should_use_incremental_field: bool, expects_from_date: bool
    ) -> None:
        result = self._driver().run(
            "scans",
            [
                self._token(),
                ScriptedResponse(json={"scans": [{"id": "s1", "createdAt": "2026-02-01T00:00:00Z"}], "totalCount": 1}),
            ],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC) if should_use_incremental_field else None,
        )

        assert result.raised is None
        request = result.requests[1]
        if expects_from_date:
            assert request.param("from-date") == "2026-01-15T00:00:00Z"
        else:
            assert request.param("from-date") is None

    def test_get_rows_resumes_from_saved_offset(self) -> None:
        result = self._driver().run(
            "projects",
            [self._token(), ScriptedResponse(json={"projects": [{"id": "p1"}], "totalCount": 201})],
            resume_state=CheckmarxResumeConfig(offset=200),
        )

        assert result.raised is None
        assert result.params("offset")[1:] == ["200"]

    # ---- fan-out over scans ----

    def _fan_out_handler(
        self, results_by_scan: dict[str, list[dict[str, Any]]]
    ) -> Callable[[RecordedRequest], ScriptedResponse]:
        scans = [
            {"id": scan_id, "createdAt": f"2026-02-0{i + 1}T00:00:00Z"}
            for i, scan_id in enumerate(results_by_scan.keys())
        ]

        def handler(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/token"):
                return self._token()
            if request.path == "/api/scans":
                return ScriptedResponse(json={"scans": scans, "totalCount": len(scans)})
            if request.path == "/api/results":
                return ScriptedResponse(
                    json={"results": results_by_scan[request.param("scan-id") or ""], "totalCount": 1}
                )
            if request.path == "/api/scan-summary":
                return ScriptedResponse(
                    json={"scansSummaries": [{"scanId": request.param("scan-ids")}], "totalCount": 1}
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        return handler

    def test_scan_results_incremental_applies_lookback_to_scan_enumeration(self) -> None:
        result = self._driver().run(
            "scan_results",
            self._fan_out_handler({"s1": [{"type": "sast", "id": "r1"}]}),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
        )

        assert result.raised is None
        scans_request = next(request for request in result.requests if request.path == "/api/scans")
        assert scans_request.param("from-date") == "2026-01-08T00:00:00Z"

    def test_scan_results_resumes_from_bookmarked_parent(self) -> None:
        handler = self._fan_out_handler(
            {
                "s1": [{"type": "sast", "id": "r1"}],
                "s2": [{"type": "sast", "id": "r2"}],
            }
        )
        result = self._driver().run(
            "scan_results", handler, resume_state=CheckmarxResumeConfig(offset=0, parent_id="s2")
        )

        assert result.raised is None
        assert [row["scan_id"] for row in result.rows] == ["s2"]
        requested_scan_ids = [request.param("scan-id") for request in result.requests if request.path == "/api/results"]
        assert requested_scan_ids == ["s2"]

    # ---- lookup endpoints ----

    @pytest.mark.parametrize(
        ("endpoint", "path", "values"),
        [
            ("result_states", "/api/lists/states", ["TO_VERIFY", "CONFIRMED"]),
            ("result_statuses", "/api/lists/statuses", ["NEW", "RECURRENT", "FIXED"]),
            ("result_severities", "/api/lists/severities", ["CRITICAL", "HIGH"]),
        ],
    )
    def test_lists_endpoints_wrap_bare_strings_and_skip_pagination(
        self, endpoint: str, path: str, values: list[str]
    ) -> None:
        result = self._driver().run(endpoint, [self._token(), ScriptedResponse(json=values)])

        assert result.raised is None
        assert result.items == [[{"value": value} for value in values]]
        # A single unpaginated request: sending offset/limit to these endpoints would be meaningless,
        # and the source must not checkpoint resume state for a collection it read in one go.
        assert result.paths[1:] == [path]
        assert result.requests[1].query == {}
        assert result.saved_states == []

    # ---- fan-out over applications ----

    # ---- fan-out over projects ----

    def _changelog_handler(
        self, changes_by_project: dict[str, list[dict[str, Any]]]
    ) -> Callable[[RecordedRequest], ScriptedResponse]:
        projects = [
            {"id": project_id, "createdAt": f"2026-03-0{i + 1}T00:00:00Z"}
            for i, project_id in enumerate(changes_by_project)
        ]

        def handler(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/token"):
                return self._token()
            if request.path == "/api/projects":
                return ScriptedResponse(json={"projects": projects, "totalCount": len(projects)})
            if request.path == "/api/sast-results-predicates/changelog":
                changes = changes_by_project[request.param("entityId") or ""]
                offset = int(request.param("offset") or 0)
                limit = int(request.param("limit") or 0)
                page = changes[offset : offset + limit]
                return ScriptedResponse(json={"results": page, "totalSimilarityIds": f"presenting x of {len(changes)}"})
            raise AssertionError(f"Unexpected URL: {request.url}")

        return handler

    def test_predicates_changelog_paginates_and_bookmarks_each_project(self) -> None:
        page_size = CHECKMARX_ENDPOINTS["sast_predicates_changelog"].page_size
        changes = [{"change": f"change {i}", "date": "2026-03-05T09:00:00Z"} for i in range(page_size + 1)]
        result = self._driver().run(
            "sast_predicates_changelog", self._changelog_handler({"proj-1": changes, "proj-2": []})
        )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [page_size, 1]
        assert [request.param("offset") for request in result.requests if request.path.endswith("/changelog")] == [
            "0",
            str(page_size),
            "0",
        ]
        assert result.saved_states == [
            CheckmarxResumeConfig(offset=page_size, parent_id="proj-1"),
            CheckmarxResumeConfig(offset=0, parent_id="proj-2"),
        ]

    # ---- validate_credentials ----

    @pytest.mark.parametrize(
        ("projects_status", "expected_valid"),
        [(200, True), (403, False)],
    )
    def test_validate_credentials_probes_projects(self, projects_status: int, expected_valid: bool) -> None:
        with scripted_network(
            [self._token(), ScriptedResponse(status=projects_status, json={"projects": []})]
        ) as network:
            valid, error = validate_credentials("my-tenant", "us", "key")

        assert [request.path for request in network.requests_log] == [
            "/auth/realms/my-tenant/protocol/openid-connect/token",
            "/api/projects",
        ]
        assert network.requests_log[1].param("offset") == "0"
        assert network.requests_log[1].param("limit") == "1"
        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_validate_credentials_bad_api_key(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={"error": "invalid_grant"})]) as network:
            valid, error = validate_credentials("my-tenant", "us", "bad-key")

        assert [request.path for request in network.requests_log] == [
            "/auth/realms/my-tenant/protocol/openid-connect/token"
        ]
        assert valid is False
        assert error is not None
        assert AUTH_ERROR_PREFIX in error

    def test_validate_credentials_unknown_region(self) -> None:
        valid, error = validate_credentials("my-tenant", "mars", "key")

        assert valid is False
        assert error is not None
        assert "region" in error.lower()

    # ---- SourceResponse assembly ----

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_checkmarx_source_response_shape(self, endpoint: str) -> None:
        config = CHECKMARX_ENDPOINTS[endpoint]
        result = self._driver().run(
            endpoint,
            [self._token(), ScriptedResponse(json=[] if config.scalar_row_field else {})],
        )
        assert result.raised is None
        response = result.response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == ("desc" if config.incremental_fields else "asc")
        if config.partition_key is None:
            # The lookup tables carry no datetime column, so there is nothing to partition on.
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
