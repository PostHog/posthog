import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.newsdata import (
    NEWSDATA_BASE_URL,
    NewsDataResumeConfig,
    _to_from_date,
    newsdata_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the newsdata module.
NEWSDATA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.newsdata.make_tracked_session"
)
# Backoff sleeps happen inside tenacity; patch its clock so retry tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(body: Any, *, status: int = 200, reason: str = "OK", compact: bool = False) -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp.url = f"{NEWSDATA_BASE_URL}/latest"
    resp.headers["Content-Type"] = "application/json"
    # NewsData serializes error envelopes compactly (no whitespace); mirror that so the
    # response_actions content match reflects the real API body.
    separators = (",", ":") if compact else None
    resp._content = b"" if body is None else json.dumps(body, separators=separators).encode()
    return resp


def _page(results: list[dict[str, Any]], next_page: str | None) -> dict[str, Any]:
    return {"status": "success", "results": results, "nextPage": next_page}


def _make_manager(resume_state: NewsDataResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Wire a mock session, snapshotting each request's params and auth AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy is taken per page.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    auth_snapshots: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        auth_snapshots.append(request.auth)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, auth_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock | None = None, **kwargs: Any) -> Any:
    return newsdata_source(
        api_key="pub_test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


class TestToFromDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2024, 1, 15, 12, 34, 56, tzinfo=UTC), "2024-01-15"),
            ("naive_datetime", datetime(2024, 1, 15, 12, 34, 56), "2024-01-15"),
            ("date_value", date(2024, 1, 15), "2024-01-15"),
            ("api_string", "2024-01-15 12:34:56", "2024-01-15"),
            ("none", None, None),
        ]
    )
    def test_to_from_date(self, _name: str, value: Any, expected: str | None) -> None:
        assert _to_from_date(value) == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_page_until_absent(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, auths = _wire(
            session,
            [_response(_page([{"article_id": "a1"}], "p2")), _response(_page([{"article_id": "a2"}], None))],
        )

        rows = _rows(_source("latest"))

        assert [r["article_id"] for r in rows] == ["a1", "a2"]
        assert session.send.call_count == 2
        # The opaque `nextPage` cursor is echoed back as the `page` query param on the next request.
        assert "page" not in params[0]
        assert params[1]["page"] == "p2"
        # The key rides on framework api_key auth (X-ACCESS-KEY header), never a query param.
        assert auths[0].name == "X-ACCESS-KEY"
        assert auths[0].location == "header"
        assert "apikey" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sources_endpoint_never_paginates(self, MockSession: mock.MagicMock) -> None:
        # /sources rejects the `page` param, so even a stray nextPage in the body must not trigger a
        # second request.
        session = MockSession.return_value
        _wire(session, [_response({"status": "success", "results": [{"id": "bbc"}], "nextPage": "ignored"})])

        rows = _rows(_source("sources"))

        assert [r["id"] for r in rows] == ["bbc"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _auths = _wire(session, [_response(_page([{"article_id": "a3"}], None))])

        manager = _make_manager(NewsDataResumeConfig(next_page="saved_cursor"))
        rows = _rows(_source("latest", manager))

        assert [r["article_id"] for r in rows] == ["a3"]
        # The saved cursor seeds the very first request.
        assert params[0]["page"] == "saved_cursor"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_cursor_after_yielding_page(self, MockSession: mock.MagicMock) -> None:
        # State is persisted AFTER a page is yielded (never before) and only while a next page
        # remains — a crash re-yields the next page rather than skipping it.
        session = MockSession.return_value
        _wire(
            session,
            [_response(_page([{"article_id": "a1"}], "p2")), _response(_page([{"article_id": "a2"}], None))],
        )

        manager = _make_manager()
        _rows(_source("latest", manager))

        # Only the first page has a following page, so exactly one cursor is saved, pointing at it.
        assert [c.args[0] for c in manager.save_state.call_args_list] == [NewsDataResumeConfig(next_page="p2")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_results_key_yields_no_rows(self, MockSession: mock.MagicMock) -> None:
        # A 200 body without `results` is the API's "no data" signal — an empty page, not an error.
        session = MockSession.return_value
        _wire(session, [_response({"status": "success"})])

        assert _rows(_source("latest")) == []
        assert session.send.call_count == 1


class TestIncrementalFromDate:
    @parameterized.expand(
        [
            # /latest and /sources reject from_date entirely, so it must never be sent even when the
            # sync is incremental — doing so 4xxs the whole run.
            ("latest_incremental", "latest", True, datetime(2024, 1, 15, tzinfo=UTC)),
            ("sources_incremental", "sources", True, datetime(2024, 1, 15, tzinfo=UTC)),
            # A date-filter endpoint syncing full-refresh sends no window either.
            ("archive_full_refresh", "archive", False, datetime(2024, 1, 15, tzinfo=UTC)),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_from_date(
        self, _name: str, endpoint: str, incremental: bool, watermark: Any, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        params, _auths = _wire(session, [_response(_page([{"article_id": "x"}], None))])

        _rows(_source(endpoint, should_use_incremental_field=incremental, db_incremental_field_last_value=watermark))

        assert "from_date" not in params[0]

    @parameterized.expand([("archive",), ("crypto",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_uses_watermark_date(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _auths = _wire(session, [_response(_page([{"article_id": "x"}], None))])

        _rows(
            _source(
                endpoint,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert params[0]["from_date"] == "2024-03-04"

    @parameterized.expand([("archive",), ("crypto",)])
    @freeze_time("2026-06-15T12:00:00Z")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_sync_applies_lookback_floor(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        # Without a watermark the first sync must floor at the trailing lookback window instead of
        # crawling the entire (up to 7-year) archive.
        session = MockSession.return_value
        params, _auths = _wire(session, [_response(_page([{"article_id": "x"}], None))])

        _rows(_source(endpoint, should_use_incremental_field=True, db_incremental_field_last_value=None))

        assert params[0]["from_date"] == "2026-05-16"


class TestErrorBody:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_status_error_body_raises(self, MockSession: mock.MagicMock) -> None:
        # NewsData reports hard failures (unsupported param, quota exhausted) in a 200-body envelope;
        # fail loud instead of silently syncing 0 rows.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    {"status": "error", "results": {"message": "quota exceeded", "code": "TooManyRequests"}},
                    compact=True,
                )
            ],
        )

        with pytest.raises(ValueError):
            _rows(_source("latest"))


class TestRetries:
    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_raises(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status=status, reason=reason)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("latest"))
        assert session.send.call_count == 5

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_then_success_recovers(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_response({}, status=429, reason="Too Many Requests"), _response(_page([{"article_id": "a1"}], None))],
        )

        rows = _rows(_source("latest"))

        assert [r["article_id"] for r in rows] == ["a1"]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_http_error_without_retry(
        self, _name: str, status: int, reason: str, MockSession: mock.MagicMock
    ) -> None:
        # 401/403 are credential/permission failures — never retried, surfaced as an HTTPError whose
        # message carries the stable status text that get_non_retryable_errors matches on.
        session = MockSession.return_value
        _wire(session, [_response({"status": "error"}, status=status, reason=reason, compact=True)])

        with pytest.raises(requests.HTTPError) as exc_info:
            _rows(_source("latest"))
        assert f"{status} Client Error" in str(exc_info.value)
        assert "https://newsdata.io" in str(exc_info.value)
        assert session.send.call_count == 1


class TestSourceResponseMetadata:
    @parameterized.expand(
        [
            ("latest", ["article_id"], "pubDate", "asc"),
            ("archive", ["article_id"], "pubDate", "desc"),
            ("crypto", ["article_id"], "pubDate", "desc"),
        ]
    )
    def test_partitioned_endpoints(
        self, endpoint: str, primary_keys: list[str], partition_key: str, sort_mode: str
    ) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]

    def test_sources_endpoint_is_unpartitioned(self) -> None:
        response = _source("sources")
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(NEWSDATA_SESSION_PATCH, return_value=session):
            assert validate_credentials("pub_test") is expected

    def test_network_failure_is_false(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(NEWSDATA_SESSION_PATCH, return_value=session):
            assert validate_credentials("pub_test") is False
