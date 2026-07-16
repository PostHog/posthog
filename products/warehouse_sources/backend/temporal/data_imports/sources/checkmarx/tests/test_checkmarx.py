from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx import (
    AUTH_ERROR_PREFIX,
    CheckmarxAuth,
    CheckmarxAuthError,
    CheckmarxResumeConfig,
    CheckmarxRetryableError,
    _build_incremental_value,
    _result_id,
    checkmarx_source,
    get_region_hosts,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.settings import (
    CHECKMARX_ENDPOINTS,
    ENDPOINTS,
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


def _make_manager(resume: CheckmarxResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _make_logger() -> MagicMock:
    return MagicMock()


class TestCheckmarx:
    # ---- auth ----

    def test_auth_exchanges_api_key_and_caches_token(self) -> None:
        session = FakeSession(lambda url, params: _response())
        auth = CheckmarxAuth(session, "https://iam.checkmarx.net", "my-tenant", "refresh-token")  # type: ignore[arg-type]

        assert auth.get_token() == "jwt-token"
        assert auth.get_token() == "jwt-token"

        assert len(session.post_calls) == 1
        url, data = session.post_calls[0]
        assert url == "https://iam.checkmarx.net/auth/realms/my-tenant/protocol/openid-connect/token"
        assert data == {"grant_type": "refresh_token", "client_id": "ast-app", "refresh_token": "refresh-token"}

    def test_auth_refreshes_expired_token(self) -> None:
        session = FakeSession(lambda url, params: _response())
        auth = CheckmarxAuth(session, "https://iam.checkmarx.net", "my-tenant", "refresh-token")  # type: ignore[arg-type]

        auth.get_token()
        auth._expires_at = 0.0  # simulate expiry
        auth.get_token()

        assert len(session.post_calls) == 2

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

    @pytest.mark.parametrize(
        ("region", "api_host", "iam_host"),
        [
            ("us", "https://ast.checkmarx.net", "https://iam.checkmarx.net"),
            ("eu", "https://eu.ast.checkmarx.net", "https://eu.iam.checkmarx.net"),
            ("sng", "https://sng.ast.checkmarx.net", "https://sng.iam.checkmarx.net"),
        ],
    )
    def test_get_region_hosts(self, region: str, api_host: str, iam_host: str) -> None:
        assert get_region_hosts(region) == (api_host, iam_host)

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

    @pytest.mark.parametrize(
        ("should_use", "value"),
        [(False, datetime(2026, 1, 15, tzinfo=UTC)), (True, None), (False, None)],
    )
    def test_build_incremental_value_disabled(self, should_use: bool, value: Any) -> None:
        assert _build_incremental_value(CHECKMARX_ENDPOINTS["scans"], should_use, value) is None

    # ---- result id ----

    @pytest.mark.parametrize(
        ("item", "expected"),
        [
            ({"type": "sast", "id": "abc", "similarityId": "sim"}, "sast:abc"),
            ({"type": "sca", "similarityId": "sim-1"}, "sca:sim-1"),
        ],
    )
    def test_result_id_prefers_id_then_similarity_id(self, item: dict[str, Any], expected: str) -> None:
        assert _result_id(item) == expected

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

        def handler(url: str, params: dict[str, Any]) -> MagicMock:
            assert url == "https://ast.checkmarx.net/api/projects"
            if params["offset"] == 0:
                return _response(payload={"projects": full_page, "totalCount": page_size + 1})
            return _response(payload={"projects": short_page, "totalCount": page_size + 1})

        session = FakeSession(handler)
        manager = _make_manager()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="projects",
                    logger=_make_logger(),
                    resumable_source_manager=manager,
                )
            )

        assert [len(batch) for batch in batches] == [page_size, 1]
        assert [call[1]["offset"] for call in session.get_calls] == [0, page_size]
        # State saved after the yielded full page, pointing at the next offset.
        manager.save_state.assert_called_once_with(CheckmarxResumeConfig(offset=page_size))

    def test_get_rows_empty_first_page_yields_nothing(self) -> None:
        session = FakeSession(lambda url, params: _response(payload={"applications": [], "totalCount": 0}))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="applications",
                    logger=_make_logger(),
                    resumable_source_manager=_make_manager(),
                )
            )

        assert batches == []

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "expects_from_date"),
        [(True, True), (False, False)],
    )
    def test_get_rows_scans_incremental_filter(
        self, should_use_incremental_field: bool, expects_from_date: bool
    ) -> None:
        def handler(url: str, params: dict[str, Any]) -> MagicMock:
            return _response(payload={"scans": [{"id": "s1", "createdAt": "2026-02-01T00:00:00Z"}], "totalCount": 1})

        session = FakeSession(handler)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="scans",
                    logger=_make_logger(),
                    resumable_source_manager=_make_manager(),
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC)
                    if should_use_incremental_field
                    else None,
                )
            )

        _url, params, _headers = session.get_calls[0]
        if expects_from_date:
            assert params["from-date"] == "2026-01-15T00:00:00Z"
        else:
            assert "from-date" not in params

    def test_get_rows_resumes_from_saved_offset(self) -> None:
        def handler(url: str, params: dict[str, Any]) -> MagicMock:
            return _response(payload={"projects": [{"id": "p1"}], "totalCount": 201})

        session = FakeSession(handler)
        manager = _make_manager(CheckmarxResumeConfig(offset=200))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="projects",
                    logger=_make_logger(),
                    resumable_source_manager=manager,
                )
            )

        assert session.get_calls[0][1]["offset"] == 200

    def test_get_rows_sends_bearer_and_versioned_accept_headers(self) -> None:
        session = FakeSession(lambda url, params: _response(payload={"projects": []}))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="projects",
                    logger=_make_logger(),
                    resumable_source_manager=_make_manager(),
                )
            )

        _url, _params, headers = session.get_calls[0]
        assert headers["Authorization"] == "Bearer jwt-token"
        assert headers["Accept"] == "application/json; version=1.0"

    # ---- fan-out over scans ----

    def _fan_out_handler(
        self, results_by_scan: dict[str, list[dict[str, Any]]]
    ) -> Callable[[str, dict[str, Any]], MagicMock]:
        scans = [
            {"id": scan_id, "createdAt": f"2026-02-0{i + 1}T00:00:00Z"}
            for i, scan_id in enumerate(results_by_scan.keys())
        ]

        def handler(url: str, params: dict[str, Any]) -> MagicMock:
            if url.endswith("/api/scans"):
                return _response(payload={"scans": scans, "totalCount": len(scans)})
            if url.endswith("/api/results"):
                return _response(payload={"results": results_by_scan[params["scan-id"]], "totalCount": 1})
            if url.endswith("/api/scan-summary"):
                return _response(payload={"scansSummaries": [{"scanId": params["scan-ids"]}], "totalCount": 1})
            raise AssertionError(f"Unexpected URL: {url}")

        return handler

    def test_scan_results_rows_carry_scan_context_and_result_id(self) -> None:
        handler = self._fan_out_handler(
            {
                "s1": [{"type": "sast", "id": "r1", "severity": "HIGH"}],
                "s2": [{"type": "sca", "similarityId": "sim-9", "severity": "LOW"}],
            }
        )
        session = FakeSession(handler)
        manager = _make_manager()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="scan_results",
                    logger=_make_logger(),
                    resumable_source_manager=manager,
                )
            )

        rows = [row for batch in batches for row in batch]
        assert [row["scan_id"] for row in rows] == ["s1", "s2"]
        assert [row["result_id"] for row in rows] == ["sast:r1", "sca:sim-9"]
        assert rows[0]["scan_created_at"] == "2026-02-01T00:00:00Z"
        assert rows[1]["scan_created_at"] == "2026-02-02T00:00:00Z"
        # Bookmark advanced to the second scan after the first one finished.
        manager.save_state.assert_called_once_with(CheckmarxResumeConfig(offset=0, scan_id="s2"))

    def test_scan_results_incremental_applies_lookback_to_scan_enumeration(self) -> None:
        handler = self._fan_out_handler({"s1": [{"type": "sast", "id": "r1"}]})
        session = FakeSession(handler)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="scan_results",
                    logger=_make_logger(),
                    resumable_source_manager=_make_manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 15, tzinfo=UTC),
                )
            )

        scans_call_params = next(params for url, params, _headers in session.get_calls if url.endswith("/api/scans"))
        assert scans_call_params["from-date"] == "2026-01-08T00:00:00Z"

    def test_scan_results_resumes_from_bookmarked_scan(self) -> None:
        handler = self._fan_out_handler(
            {
                "s1": [{"type": "sast", "id": "r1"}],
                "s2": [{"type": "sast", "id": "r2"}],
            }
        )
        session = FakeSession(handler)
        manager = _make_manager(CheckmarxResumeConfig(offset=0, scan_id="s2"))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="scan_results",
                    logger=_make_logger(),
                    resumable_source_manager=manager,
                )
            )

        rows = [row for batch in batches for row in batch]
        assert [row["scan_id"] for row in rows] == ["s2"]
        requested_scan_ids = [
            params["scan-id"] for url, params, _headers in session.get_calls if url.endswith("/api/results")
        ]
        assert requested_scan_ids == ["s2"]

    def test_scan_results_restarts_when_bookmarked_scan_is_gone(self) -> None:
        handler = self._fan_out_handler({"s1": [{"type": "sast", "id": "r1"}]})
        session = FakeSession(handler)
        manager = _make_manager(CheckmarxResumeConfig(offset=100, scan_id="deleted-scan"))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="scan_results",
                    logger=_make_logger(),
                    resumable_source_manager=manager,
                )
            )

        rows = [row for batch in batches for row in batch]
        assert [row["scan_id"] for row in rows] == ["s1"]
        # The stale offset must not leak into the restarted scan.
        results_offsets = [
            params["offset"] for url, params, _headers in session.get_calls if url.endswith("/api/results")
        ]
        assert results_offsets == [0]

    def test_scan_results_summary_requests_one_scan_per_call(self) -> None:
        handler = self._fan_out_handler({"s1": [], "s2": []})
        session = FakeSession(handler)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    tenant_name="my-tenant",
                    region="us",
                    api_key="key",
                    endpoint="scan_results_summary",
                    logger=_make_logger(),
                    resumable_source_manager=_make_manager(),
                )
            )

        rows = [row for batch in batches for row in batch]
        assert [row["scan_id"] for row in rows] == ["s1", "s2"]
        summary_calls = [params for url, params, _headers in session.get_calls if url.endswith("/api/scan-summary")]
        assert [params["scan-ids"] for params in summary_calls] == ["s1", "s2"]

    # ---- validate_credentials ----

    @pytest.mark.parametrize(
        ("projects_status", "expected_valid"),
        [(200, True), (403, False)],
    )
    def test_validate_credentials_probes_projects(self, projects_status: int, expected_valid: bool) -> None:
        session = FakeSession(lambda url, params: _response(status=projects_status, payload={"projects": []}))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            valid, error = validate_credentials("my-tenant", "us", "key")

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_validate_credentials_bad_api_key(self) -> None:
        token_response = _response(status=401, payload={"error": "invalid_grant"})
        session = FakeSession(lambda url, params: _response(), token_response=token_response)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx.make_tracked_session",
            return_value=session,
        ):
            valid, error = validate_credentials("my-tenant", "us", "bad-key")

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
        response = checkmarx_source(
            tenant_name="my-tenant",
            region="us",
            api_key="key",
            endpoint=endpoint,
            logger=_make_logger(),
            resumable_source_manager=_make_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == ("desc" if config.incremental_fields else "asc")
        assert response.partition_keys == [config.partition_key]
        assert response.partition_mode == "datetime"
