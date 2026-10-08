import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.news_api import (
    PAGE_SIZE,
    NewsApiResumeConfig,
    _format_from_value,
    news_api_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the news_api module.
NEWS_API_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.news_api.news_api.make_tracked_session"
)


def _response(body: dict[str, Any], *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: NewsApiResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, *, language: str | None = None, **kwargs: Any) -> Any:
    return news_api_source(
        api_key="k",
        endpoint=endpoint,
        query="bitcoin",
        language=language,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatFromValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "2026-03-04T00:00:00", "2026-03-04T00:00:00"),
            ("empty_string", "", None),
            ("none", None, None),
        ]
    )
    def test_format_from_value(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_from_value(value) == expected


class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_everything_incremental_includes_from_sort_and_language(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"totalResults": 1, "articles": [{"url": "a"}]})])

        _rows(
            _source(
                "everything",
                _make_manager(),
                language="en",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert params[0]["q"] == "bitcoin"
        assert params[0]["sortBy"] == "publishedAt"
        assert params[0]["pageSize"] == PAGE_SIZE
        assert params[0]["page"] == 1
        assert params[0]["language"] == "en"
        assert params[0]["from"] == "2026-03-04T02:58:14"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sources_ignores_query_and_pagination(self, MockSession: Any) -> None:
        # /v2/top-headlines/sources takes neither q nor pagination; only optional facet filters.
        session = MockSession.return_value
        params = _wire(session, [_response({"sources": [{"id": "bbc-news"}]})])

        _rows(_source("sources", _make_manager(), language="en"))

        assert params[0] == {"language": "en"}


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: Any) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response({"totalResults": 150, "articles": [{"url": "resumed"}]})])

        manager = _make_manager(NewsApiResumeConfig(next_page=2))
        rows = _rows(_source("everything", manager))

        # It must start at page 2 (not page 1) so the saved cursor is honored.
        assert params[0]["page"] == 2
        assert [r["url"] for r in rows] == ["resumed"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_with_missing_total_keeps_paging(self, MockSession: Any) -> None:
        # A full page with `totalResults` absent must not stop the walk. The short page 2 ends it.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"articles": [{"url": f"u{i}"} for i in range(PAGE_SIZE)]}),
                _response({"articles": [{"url": "tail"}]}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("everything", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_other_client_error_propagates(self, MockSession: Any) -> None:
        # A 426 without `maximumResultsReached` (or any other 4xx) is a real failure — surface it.
        session = MockSession.return_value
        _wire(session, [_response({"status": "error", "code": "parameterInvalid"}, status=426)])

        manager = _make_manager()
        with pytest.raises(requests.HTTPError):
            _rows(_source("everything", manager))


class TestRetry:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_codes_retry(self, _name: str, status: int, MockSession: Any, _sleep: Any) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"status": "error"}, status=status),
                _response({"totalResults": 1, "articles": [{"url": "a"}]}),
            ],
        )

        rows = _rows(_source("everything", _make_manager()))

        assert [r["url"] for r in rows] == ["a"]
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_without_retry(self, MockSession: Any, _sleep: Any) -> None:
        # A 401 is a permanent credential failure — it must surface at once, not burn retries.
        session = MockSession.return_value
        _wire(session, [_response({"status": "error", "code": "apiKeyInvalid"}, status=401)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("everything", _make_manager()))

        assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False)])
    @mock.patch(NEWS_API_SESSION_PATCH)
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool, mock_session: Any) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("k") is expected


class TestSourceResponse:
    @parameterized.expand(
        [
            # Only the incremental endpoint declares desc — the full-refresh tables have no watermark
            # to protect, so their arrival order stays on the default.
            ("everything", ["url"], "desc"),
            ("top_headlines", ["url"], "asc"),
            ("sources", ["id"], "asc"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_and_sort_mode_per_endpoint(
        self, endpoint: str, expected_keys: list[str], expected_sort: str, MockSession: Any
    ) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == expected_sort

    @parameterized.expand([("everything", "publishedAt"), ("top_headlines", "publishedAt"), ("sources", None)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partition_key_per_endpoint(self, endpoint: str, expected_partition: str | None, MockSession: Any) -> None:
        response = _source(endpoint, _make_manager())
        if expected_partition is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"
