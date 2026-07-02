from collections.abc import Callable
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from tenacity import RetryCallState

from products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion import (
    MAX_BLOCK_DEPTH,
    MAX_CHILD_PAGES_PER_PARENT,
    MAX_RETRY_AFTER_SECONDS,
    NOTION_VERSION,
    NotionBadRequestError,
    NotionNotFoundError,
    NotionResumeConfig,
    NotionRetryableError,
    _comments_stream,
    _get_headers,
    _iter_block_children,
    _parse_retry_after,
    _request,
    _search_body,
    _search_stream,
    _wait_strategy,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.settings import NOTION_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion"


class FakeResponse:
    def __init__(self, json_data: Any, status_code: int = 200, headers: Optional[dict[str, str]] = None) -> None:
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {}
        self.ok = 200 <= status_code < 400
        self.text = ""

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=cast(requests.Response, self))


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | Callable[[int], FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def _next(self) -> FakeResponse:
        index = len(self.calls) - 1
        if callable(self._responses):
            return self._responses(index)
        return self._responses.pop(0)

    def request(
        self,
        method: str,
        url: str,
        json: Any = None,
        params: Any = None,
        timeout: Any = None,
    ) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "json": json, "params": params})
        return self._next()

    def get(self, url: str, timeout: Any = None) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url})
        return self._next()


def _list_response(results: list[dict[str, Any]], has_more: bool, next_cursor: str | None) -> FakeResponse:
    return FakeResponse({"results": results, "has_more": has_more, "next_cursor": next_cursor})


class _FakeRetryState:
    """Minimal RetryCallState stand-in carrying just the failing outcome."""

    def __init__(self, exception: BaseException) -> None:
        self.outcome = mock.MagicMock()
        self.outcome.exception.return_value = exception


class TestNotion:
    def test_headers_include_bearer_token_and_version(self) -> None:
        headers = _get_headers("ntn_secret")
        assert headers["Authorization"] == "Bearer ntn_secret"
        assert headers["Notion-Version"] == NOTION_VERSION
        assert headers["Content-Type"] == "application/json"

    @parameterized.expand([("page",), ("data_source",)])
    def test_search_body_shape(self, object_filter: str) -> None:
        body = _search_body(object_filter, None)
        assert body["filter"] == {"property": "object", "value": object_filter}
        assert body["sort"] == {"timestamp": "last_edited_time", "direction": "ascending"}
        assert body["page_size"] == 100
        assert "start_cursor" not in body

    def test_search_body_includes_cursor_when_set(self) -> None:
        body = _search_body("page", "cursor-123")
        assert body["start_cursor"] == "cursor-123"

    def test_search_stream_paginates_and_terminates(self) -> None:
        session = FakeSession(
            [
                _list_response([{"id": "p1"}], has_more=True, next_cursor="c1"),
                _list_response([{"id": "p2"}], has_more=False, next_cursor=None),
            ]
        )
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        tables = list(
            _search_stream(cast(requests.Session, session), NOTION_ENDPOINTS["pages"], mock.MagicMock(), manager)
        )

        total_rows = sum(t.num_rows for t in tables)
        assert total_rows == 2
        # Two pages fetched, then the loop terminates on has_more=False.
        assert len(session.calls) == 2

    def test_search_stream_resumes_from_saved_cursor(self) -> None:
        session = FakeSession([_list_response([{"id": "p1"}], has_more=False, next_cursor=None)])
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = NotionResumeConfig(next_cursor="resume-cursor")

        list(_search_stream(cast(requests.Session, session), NOTION_ENDPOINTS["pages"], mock.MagicMock(), manager))

        # The first request must start from the persisted cursor.
        assert session.calls[0]["json"]["start_cursor"] == "resume-cursor"

    def test_block_children_inject_page_id(self) -> None:
        session = FakeSession([_list_response([{"id": "b1", "has_children": False}], has_more=False, next_cursor=None)])
        blocks = list(
            _iter_block_children(cast(requests.Session, session), "block-root", "page-42", mock.MagicMock(), 0)
        )

        assert len(blocks) == 1
        assert blocks[0]["_page_id"] == "page-42"

    def test_block_children_respect_depth_limit(self) -> None:
        # Every fetched block has children, so recursion would be unbounded without the depth cap.
        def always_has_children(_index: int) -> FakeResponse:
            return _list_response([{"id": "child", "has_children": True}], has_more=False, next_cursor=None)

        session = FakeSession(always_has_children)
        blocks = list(
            _iter_block_children(cast(requests.Session, session), "block-root", "page-1", mock.MagicMock(), 0)
        )

        # depth 0 yields one block, then recurses up to MAX_BLOCK_DEPTH levels.
        assert len(blocks) == MAX_BLOCK_DEPTH + 1

    def test_block_children_respect_page_cap(self) -> None:
        # Endpoint always reports another page; the per-parent cap must stop the scan.
        def always_more(_index: int) -> FakeResponse:
            return _list_response([{"id": "b", "has_children": False}], has_more=True, next_cursor="next")

        session = FakeSession(always_more)
        logger = mock.MagicMock()
        blocks = list(_iter_block_children(cast(requests.Session, session), "block-root", "page-1", logger, 0))

        assert len(blocks) == MAX_CHILD_PAGES_PER_PARENT
        assert logger.warning.called

    def test_request_429_raises_retryable_with_retry_after(self) -> None:
        session = FakeSession([FakeResponse({}, status_code=429, headers={"Retry-After": "7"})])
        # Bypass the tenacity retry wrapper so we observe a single attempt's behaviour.
        with pytest.raises(NotionRetryableError) as exc_info:
            cast(Any, _request).__wrapped__(
                cast(requests.Session, session), "GET", "/v1/users", mock.MagicMock(), params={}
            )
        assert exc_info.value.retry_after == 7.0

    def test_request_5xx_raises_retryable_without_retry_after(self) -> None:
        session = FakeSession([FakeResponse({}, status_code=503)])
        with pytest.raises(NotionRetryableError) as exc_info:
            cast(Any, _request).__wrapped__(
                cast(requests.Session, session), "GET", "/v1/users", mock.MagicMock(), params={}
            )
        assert exc_info.value.retry_after is None

    def test_request_retries_chunked_encoding_error(self) -> None:
        # Notion can break the connection mid-response, which requests surfaces as a
        # ChunkedEncodingError ("Connection broken: InvalidChunkLength"). It is transient and must be
        # retried like other connection failures, not propagated as a fatal sync error.
        attempts = {"count": 0}

        def request(*_args: Any, **_kwargs: Any) -> FakeResponse:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise requests.exceptions.ChunkedEncodingError("Connection broken: InvalidChunkLength(got length b'')")
            return FakeResponse({"results": []})

        session = mock.MagicMock()
        session.request.side_effect = request

        with mock.patch(f"{MODULE}._wait_strategy", return_value=0):
            result = _request(cast(requests.Session, session), "GET", "/v1/comments", mock.MagicMock(), params={})

        assert result == {"results": []}
        assert attempts["count"] == 2

    def test_request_404_raises_not_found(self) -> None:
        # Notion 404s a page/block that was deleted or unshared. It must surface as the typed
        # NotionNotFoundError so the fan-out streams can skip it instead of crashing.
        session = FakeSession([FakeResponse({}, status_code=404)])
        with pytest.raises(NotionNotFoundError):
            cast(Any, _request).__wrapped__(
                cast(requests.Session, session), "GET", "/v1/comments", mock.MagicMock(), params={}
            )

    def test_request_404_is_not_retried(self) -> None:
        # A 404 is not transient, so tenacity must propagate it immediately rather than burn attempts.
        attempts = {"count": 0}

        def request(*_args: Any, **_kwargs: Any) -> FakeResponse:
            attempts["count"] += 1
            return FakeResponse({}, status_code=404)

        session = mock.MagicMock()
        session.request.side_effect = request

        with mock.patch(f"{MODULE}._wait_strategy", return_value=0):
            with pytest.raises(NotionNotFoundError):
                _request(cast(requests.Session, session), "GET", "/v1/comments", mock.MagicMock(), params={})

        assert attempts["count"] == 1

    def test_request_400_raises_bad_request(self) -> None:
        # Notion 400s a block it won't expand (e.g. has_children backed by synced/external content).
        # It must surface as the typed NotionBadRequestError, carrying the body so callers can log
        # Notion's `code`/`message`, so the fan-out streams can skip it.
        response = FakeResponse({}, status_code=400)
        response.text = '{"code":"validation_error","message":"boom"}'
        session = FakeSession([response])
        with pytest.raises(NotionBadRequestError) as exc_info:
            cast(Any, _request).__wrapped__(
                cast(requests.Session, session), "GET", "/v1/blocks/b1/children", mock.MagicMock(), params={}
            )
        assert "validation_error" in str(exc_info.value)

    def test_request_400_is_not_retried(self) -> None:
        # A 400 is not transient, so tenacity must propagate it immediately rather than burn attempts.
        attempts = {"count": 0}

        def request(*_args: Any, **_kwargs: Any) -> FakeResponse:
            attempts["count"] += 1
            return FakeResponse({}, status_code=400)

        session = mock.MagicMock()
        session.request.side_effect = request

        with mock.patch(f"{MODULE}._wait_strategy", return_value=0):
            with pytest.raises(NotionBadRequestError):
                _request(cast(requests.Session, session), "GET", "/v1/blocks/b1/children", mock.MagicMock(), params={})

        assert attempts["count"] == 1

    def test_block_children_skips_rejected_block(self) -> None:
        # A block Notion rejects with 400 (advertised has_children but can't be expanded) must
        # terminate that branch gracefully, yielding nothing, rather than crashing the whole sync.
        session = FakeSession([FakeResponse({}, status_code=400)])
        logger = mock.MagicMock()
        blocks = list(_iter_block_children(cast(requests.Session, session), "rejected", "page-1", logger, 0))

        assert blocks == []
        assert logger.warning.called

    def test_comments_stream_skips_rejected_page(self) -> None:
        # Notion 400s the comments fetch for one page; that page is skipped without crashing the
        # sync, and comments for the surviving page still come through.
        def responses(index: int) -> FakeResponse:
            if index == 0:
                return _list_response([{"id": "p1"}, {"id": "p2"}], has_more=False, next_cursor=None)
            if index == 1:
                return FakeResponse({}, status_code=400)  # comments for p1 -> rejected
            return _list_response([{"id": "cm"}], has_more=False, next_cursor=None)  # comments for p2

        session = FakeSession(responses)
        logger = mock.MagicMock()
        tables = list(_comments_stream(cast(requests.Session, session), logger))

        total_rows = sum(t.num_rows for t in tables)
        assert total_rows == 1
        assert logger.warning.called
        assert len(session.calls) == 3

    def test_comments_stream_skips_missing_page(self) -> None:
        # One page is deleted/unshared between search and the comments fetch (404). That page must be
        # skipped without crashing the sync; comments for the surviving page still come through.
        def responses(index: int) -> FakeResponse:
            if index == 0:
                return _list_response([{"id": "p1"}, {"id": "p2"}], has_more=False, next_cursor=None)
            if index == 1:
                return FakeResponse({}, status_code=404)  # comments for p1 -> gone
            return _list_response([{"id": "cm"}], has_more=False, next_cursor=None)  # comments for p2

        session = FakeSession(responses)
        logger = mock.MagicMock()
        tables = list(_comments_stream(cast(requests.Session, session), logger))

        total_rows = sum(t.num_rows for t in tables)
        assert total_rows == 1
        assert logger.warning.called
        # search + comments(p1, 404) + comments(p2)
        assert len(session.calls) == 3

    def test_block_children_skips_missing_block(self) -> None:
        # A block that 404s (deleted/unshared) must terminate that branch gracefully, yielding nothing.
        session = FakeSession([FakeResponse({}, status_code=404)])
        logger = mock.MagicMock()
        blocks = list(_iter_block_children(cast(requests.Session, session), "gone", "page-1", logger, 0))

        assert blocks == []
        assert logger.warning.called

    @parameterized.expand([("5", 5.0), (None, None), ("not-a-number", None)])
    def test_parse_retry_after(self, value: str | None, expected: float | None) -> None:
        assert _parse_retry_after(value) == expected

    def test_wait_strategy_honors_retry_after(self) -> None:
        state = _FakeRetryState(NotionRetryableError("rate limited", retry_after=3.0))
        assert _wait_strategy(cast(RetryCallState, state)) == 3.0

    def test_wait_strategy_honors_multi_minute_retry_after(self) -> None:
        # Notion routinely asks for several minutes under sustained load. Clamping that to the
        # exponential ceiling retried inside the penalty window and exhausted attempts, so the
        # full Retry-After must be honored.
        state = _FakeRetryState(NotionRetryableError("rate limited", retry_after=336.0))
        assert _wait_strategy(cast(RetryCallState, state)) == 336.0

    def test_wait_strategy_caps_retry_after(self) -> None:
        state = _FakeRetryState(NotionRetryableError("rate limited", retry_after=10_000.0))
        assert _wait_strategy(cast(RetryCallState, state)) == MAX_RETRY_AFTER_SECONDS

    def test_comments_stream_respects_page_cap(self) -> None:
        # First call is the page search (one page, then done); every subsequent /v1/comments
        # call reports another page, so the per-parent cap must stop the scan.
        def responses(index: int) -> FakeResponse:
            if index == 0:
                return _list_response([{"id": "p1"}], has_more=False, next_cursor=None)
            return _list_response([{"id": "cm"}], has_more=True, next_cursor="next")

        session = FakeSession(responses)
        logger = mock.MagicMock()
        list(_comments_stream(cast(requests.Session, session), logger))

        # One search call plus the capped number of comment-page fetches.
        assert len(session.calls) == 1 + MAX_CHILD_PAGES_PER_PARENT
        assert logger.warning.called

    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_validate_credentials_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        session = FakeSession([FakeResponse({}, status_code=status_code)])
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("tok")

        assert valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_validate_credentials_handles_exception(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session", side_effect=requests.ConnectionError("boom")):
            valid, message = validate_credentials("tok")

        assert valid is False
        assert message == "boom"


@pytest.mark.parametrize("endpoint", list(NOTION_ENDPOINTS.keys()))
def test_every_endpoint_has_config(endpoint: str) -> None:
    config = NOTION_ENDPOINTS[endpoint]
    assert config.name == endpoint
    assert config.stream_type in ("search", "users", "blocks", "comments")
    if config.stream_type == "search":
        assert config.object_filter in ("page", "data_source")
