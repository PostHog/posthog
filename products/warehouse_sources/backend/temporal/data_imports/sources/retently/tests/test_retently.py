from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.retently import retently
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.retently import (
    RetentlyResumeConfig,
    RetentlyRetryableError,
    _extract_items,
    _format_start_date,
    get_rows,
    retently_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.settings import (
    ENDPOINTS,
    RETENTLY_ENDPOINTS,
)


class _FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code
        self.text = str(body)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)  # type: ignore[arg-type]


class _FakeSession:
    def __init__(self, bodies: list[Any]) -> None:
        self._bodies = list(bodies)
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: Any = None) -> _FakeResponse:
        self.requests.append((url, dict(params or {})))
        body = self._bodies.pop(0)
        if isinstance(body, _FakeResponse):
            return body
        return _FakeResponse(body)


class _FakeResumableManager:
    def __init__(self, state: RetentlyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[RetentlyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> RetentlyResumeConfig | None:
        return self._state

    def save_state(self, data: RetentlyResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    endpoint: str,
    bodies: list[Any],
    manager: _FakeResumableManager | None = None,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], _FakeSession]:
    session = _FakeSession(bodies)
    rows: list[dict[str, Any]] = []
    with patch.object(retently, "make_tracked_session", return_value=session):
        for batch in get_rows(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager or _FakeResumableManager(),  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
    return rows, session


class TestExtractItems:
    @parameterized.expand(
        [
            # Records nested under `data.<key>` — feedback, outbox, customers, companies.
            ("nested_in_data", "feedback", {"data": {"responses": [{"id": "1"}], "pages": 1}}, [{"id": "1"}]),
            # /reports returns a bare list under `data`.
            ("bare_list_under_data", "reports", {"data": [{"campaignId": "c1"}]}, [{"campaignId": "c1"}]),
            # Campaigns/templates document the array at the top level, outside `data`.
            ("top_level_array", "campaigns", {"campaigns": [{"id": "c1"}]}, [{"id": "c1"}]),
            # Fallback: a single list-valued entry in `data` even when the documented key drifts.
            ("renamed_key_fallback", "customers", {"data": {"people": [{"id": "1"}], "total": 1}}, [{"id": "1"}]),
        ]
    )
    def test_documented_envelope_shapes(self, _name: str, endpoint: str, body: Any, expected: list) -> None:
        assert _extract_items(body, RETENTLY_ENDPOINTS[endpoint]) == expected

    @parameterized.expand(
        [
            ("not_a_dict", ["rows"]),
            ("no_recognisable_array", {"data": {"total": 3, "tags": ["a"], "other": ["b"]}}),
        ]
    )
    def test_unexpected_payloads_raise_retryable(self, _name: str, body: Any) -> None:
        with pytest.raises(RetentlyRetryableError):
            _extract_items(body, RETENTLY_ENDPOINTS["feedback"])


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("epoch_passthrough", 1704067200, "1704067200"),
            ("string_passthrough", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_format_start_date(self, _name: str, value: object, expected: str) -> None:
        assert _format_start_date(value) == expected


class TestPagination:
    def test_walks_pages_using_pages_metadata_inside_data(self) -> None:
        bodies = [
            {"data": {"responses": [{"id": "1"}], "page": 1, "pages": 2}},
            {"data": {"responses": [{"id": "2"}], "page": 2, "pages": 2}},
        ]
        rows, session = _collect("feedback", bodies)
        assert [r["id"] for r in rows] == ["1", "2"]
        # Stops at the last page — never requests page 3.
        assert [params["page"] for _, params in session.requests] == [1, 2]

    def test_top_level_pages_metadata_keeps_paginating(self) -> None:
        # The customers docs place `pages` at the top level; a short page must not end the loop
        # while the metadata says more pages exist (e.g. the API caps `limit` below our request).
        bodies = [
            {"data": {"subscribers": [{"id": "1"}]}, "page": 1, "pages": 2},
            {"data": {"subscribers": [{"id": "2"}]}, "page": 2, "pages": 2},
        ]
        rows, session = _collect("customers", bodies)
        assert [r["id"] for r in rows] == ["1", "2"]
        assert len(session.requests) == 2

    def test_short_page_ends_loop_without_pages_metadata(self) -> None:
        bodies = [{"data": {"responses": [{"id": "1"}]}}]
        rows, session = _collect("feedback", bodies)
        assert rows == [{"id": "1"}]
        assert len(session.requests) == 1

    def test_empty_first_page_yields_nothing(self) -> None:
        bodies = [{"data": {"responses": [], "page": 1, "pages": 0}}]
        rows, _ = _collect("feedback", bodies)
        assert rows == []

    @parameterized.expand(
        [
            ("campaigns", {"campaigns": [{"id": "c1"}]}),
            ("templates", {"templates": [{"id": "t1"}]}),
            ("reports", {"data": [{"campaignId": "c1"}]}),
        ]
    )
    def test_unpaginated_endpoints_make_one_request_without_page_params(self, endpoint: str, body: Any) -> None:
        rows, session = _collect(endpoint, [body])
        assert len(rows) == 1
        assert len(session.requests) == 1
        _, params = session.requests[0]
        assert "page" not in params
        assert "limit" not in params

    def test_requests_ascending_sort_for_page_stability(self) -> None:
        bodies = [{"data": {"surveys": [{"customerId": "1"}], "pages": 1}}]
        _, session = _collect("outbox", bodies)
        _, params = session.requests[0]
        assert params["sort"] == "surveyCreatedDate"
        assert params["limit"] == retently.PAGE_SIZE


class TestIncremental:
    def test_start_date_sent_when_incremental(self) -> None:
        bodies = [{"data": {"responses": [{"id": "1"}], "pages": 1}}]
        _, session = _collect(
            "feedback",
            bodies,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        _, params = session.requests[0]
        assert params["startDate"] == "2026-03-04T02:58:14Z"
        assert params["sort"] == "createdDate"

    @parameterized.expand(
        [
            ("full_refresh_run", False, datetime(2026, 3, 4, tzinfo=UTC)),
            ("first_incremental_run_has_no_watermark", True, None),
        ]
    )
    def test_start_date_omitted(self, _name: str, should_use: bool, last_value: Any) -> None:
        bodies = [{"data": {"responses": [{"id": "1"}], "pages": 1}}]
        _, session = _collect(
            "feedback",
            bodies,
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
        )
        _, params = session.requests[0]
        assert "startDate" not in params

    def test_full_refresh_endpoint_ignores_incremental_inputs(self) -> None:
        bodies = [{"data": {"subscribers": [{"id": "1"}], "pages": 1}}]
        _, session = _collect(
            "customers",
            bodies,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        _, params = session.requests[0]
        assert "startDate" not in params


class TestResume:
    def test_resume_starts_from_saved_page(self) -> None:
        bodies = [{"data": {"responses": [{"id": "9"}], "page": 3, "pages": 3}}]
        manager = _FakeResumableManager(RetentlyResumeConfig(page=3))
        rows, session = _collect("feedback", bodies, manager=manager)
        assert rows == [{"id": "9"}]
        assert session.requests[0][1]["page"] == 3

    def test_state_saved_after_yield_with_next_page(self) -> None:
        bodies = [
            {"data": {"responses": [{"id": "1"}], "pages": 2}},
            {"data": {"responses": [{"id": "2"}], "pages": 2}},
        ]
        manager = _FakeResumableManager()
        _collect("feedback", bodies, manager=manager)
        # Only the transition to page 2 is checkpointed; the final page saves nothing (a crash
        # after the last yield just re-fetches page 2 and merge dedupes).
        assert [state.page for state in manager.saved] == [2]


class TestRetries:
    @parameterized.expand(
        [
            ("rate_limited", _FakeResponse({}, status_code=429)),
            ("server_error", _FakeResponse({}, status_code=500)),
            # A transiently malformed payload (e.g. an HTML error page from a proxy) must retry the
            # single request, not fail the sync — extraction runs inside the retried scope.
            ("malformed_payload", "<html>bad gateway</html>"),
        ]
    )
    def test_transient_failures_are_retried(self, _name: str, first_response: Any) -> None:
        bodies = [
            first_response,
            {"data": {"responses": [{"id": "1"}], "pages": 1}},
        ]
        with (
            patch.object(retently, "MAX_RETRIES", 2),
            # No real backoff sleeps in tests.
            patch.object(retently, "wait_exponential_jitter", lambda **kwargs: wait_none()),
        ):
            rows, session = _collect("feedback", bodies)
        assert rows == [{"id": "1"}]
        assert len(session.requests) == 2

    def test_auth_error_raises_immediately(self) -> None:
        bodies = [_FakeResponse({"message": "Account not found", "code": 401, "data": None}, status_code=401)]
        with pytest.raises(requests.HTTPError):
            _collect("feedback", bodies)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Retently API key"),
            ("forbidden", 403, False, "Invalid Retently API key"),
            ("server_error_is_inconclusive", 500, False, "Retently returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_msg: str | None) -> None:
        session = _FakeSession([_FakeResponse({}, status_code=status_code)])
        with patch.object(retently, "make_tracked_session", return_value=session):
            ok, message = validate_credentials("key")
        assert ok is expected_ok
        if expected_msg is None:
            assert message is None
        else:
            assert message is not None and expected_msg in message
        assert session.requests[0][0].endswith("/ping")

    def test_network_error_is_inconclusive_not_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(retently, "make_tracked_session", return_value=session):
            ok, message = validate_credentials("key")
        assert ok is False
        assert message is not None and "Could not connect to Retently" in message


class TestSourceResponse:
    @parameterized.expand(
        [
            ("customers", ["id"], "createdDate", "asc"),
            ("companies", ["id"], "createdDate", "asc"),
            # feedback is the only incremental endpoint: "desc" defers the watermark to the end of
            # a successful sync because the API's sort behavior could not be live-verified.
            ("feedback", ["id"], "createdDate", "desc"),
            ("outbox", None, None, "asc"),
            ("campaigns", ["id"], None, "asc"),
            ("templates", ["id"], None, "asc"),
            ("reports", ["campaignId"], None, "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str] | None, partition_key: str | None, sort_mode: str
    ) -> None:
        response = retently_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"

    @parameterized.expand(ENDPOINTS)
    def test_every_declared_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = retently_source(
            api_key="key", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.name == endpoint
