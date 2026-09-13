from collections.abc import Callable
from datetime import UTC, datetime
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
    NOTION_VERSION_2025_09_03,
    NOTION_VERSION_2026_03_11,
    NotionBadRequestError,
    NotionNotFoundError,
    NotionResumeConfig,
    NotionRetryableError,
    _blocks_stream,
    _comments_stream,
    _data_source_query_body,
    _database_rows_stream,
    _flatten_database_row,
    _get_headers,
    _iter_block_children,
    _iter_page_ids,
    _parse_retry_after,
    _property_to_text,
    _request,
    _search_body,
    _search_stream,
    _users_stream,
    _wait_strategy,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.settings import NOTION_ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion"


class FakeResponse:
    def __init__(
        self,
        json_data: Any,
        status_code: int = 200,
        headers: Optional[dict[str, str]] = None,
        json_exc: Optional[Exception] = None,
    ) -> None:
        self._json = json_data
        self._json_exc = json_exc
        self.status_code = status_code
        self.headers = headers or {}
        self.ok = 200 <= status_code < 400
        self.text = ""

    def json(self) -> Any:
        if self._json_exc is not None:
            raise self._json_exc
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
        if isinstance(self._responses, list):
            return self._responses.pop(0)
        return self._responses(index)

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
    @parameterized.expand([(NOTION_VERSION_2025_09_03,), (NOTION_VERSION_2026_03_11,)])
    def test_headers_carry_requested_version(self, api_version: str) -> None:
        headers = _get_headers("ntn_secret", api_version)
        assert headers["Authorization"] == "Bearer ntn_secret"
        assert headers["Notion-Version"] == api_version
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

    @staticmethod
    def _invalid_cursor_response() -> FakeResponse:
        response = FakeResponse({}, status_code=400)
        response.text = (
            '{"object":"error","status":400,"code":"validation_error",'
            '"message":"The start_cursor provided is invalid: dead-cursor"}'
        )
        return response

    def test_search_stream_restarts_when_resumed_cursor_invalid(self) -> None:
        # A resumed search cursor can expire before the retry runs; Notion then rejects it with a 400
        # validation_error. The stream must drop the stale cursor and restart from the beginning
        # rather than crashing the whole sync.
        session = FakeSession(
            [
                self._invalid_cursor_response(),
                _list_response([{"id": "p1"}], has_more=False, next_cursor=None),
            ]
        )
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = NotionResumeConfig(next_cursor="stale-cursor")

        tables = list(
            _search_stream(cast(requests.Session, session), NOTION_ENDPOINTS["pages"], mock.MagicMock(), manager)
        )

        assert sum(t.num_rows for t in tables) == 1
        # First request replays the stale cursor (rejected); the restart carries no cursor.
        assert session.calls[0]["json"]["start_cursor"] == "stale-cursor"
        assert "start_cursor" not in session.calls[1]["json"]

    def test_search_stream_propagates_non_cursor_bad_request(self) -> None:
        # A 400 that is not the invalid-cursor case is a genuine bad request and must still fail the
        # sync rather than being silently restarted.
        other_400 = FakeResponse({}, status_code=400)
        other_400.text = '{"code":"validation_error","message":"something else"}'
        session = FakeSession([other_400])
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = NotionResumeConfig(next_cursor="stale-cursor")

        with pytest.raises(NotionBadRequestError):
            list(_search_stream(cast(requests.Session, session), NOTION_ENDPOINTS["pages"], mock.MagicMock(), manager))

    def test_users_stream_restarts_when_resumed_cursor_invalid(self) -> None:
        # The users stream persists the same kind of resume cursor as search, so a stale cursor must
        # trigger the same restart-from-the-beginning recovery rather than crashing the sync.
        session = FakeSession(
            [
                self._invalid_cursor_response(),
                _list_response([{"id": "u1"}], has_more=False, next_cursor=None),
            ]
        )
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = NotionResumeConfig(next_cursor="stale-cursor")

        tables = list(_users_stream(cast(requests.Session, session), mock.MagicMock(), manager))

        assert sum(t.num_rows for t in tables) == 1
        assert session.calls[0]["params"]["start_cursor"] == "stale-cursor"
        assert "start_cursor" not in session.calls[1]["params"]

    def test_iter_page_ids_restarts_when_cursor_invalid(self) -> None:
        # A page-id search cursor can expire mid-enumeration on a large workspace, which Notion
        # rejects with the same 400 validation_error as the search/users streams. The blocks/comments
        # fan-out must restart enumeration rather than crashing the whole sync.
        session = FakeSession(
            [
                _list_response([{"id": "p1"}], has_more=True, next_cursor="c1"),
                self._invalid_cursor_response(),
                _list_response([{"id": "p1"}], has_more=False, next_cursor=None),
            ]
        )
        logger = mock.MagicMock()

        page_ids = list(_iter_page_ids(cast(requests.Session, session), logger))

        assert page_ids == ["p1", "p1"]
        assert logger.warning.called
        # Second request replays the now-stale cursor (rejected); the restart carries no cursor.
        assert session.calls[1]["json"]["start_cursor"] == "c1"
        assert "start_cursor" not in session.calls[2]["json"]

    def test_iter_page_ids_propagates_non_cursor_bad_request(self) -> None:
        # A 400 that is not the invalid-cursor case is a genuine bad request and must still fail the
        # sync rather than being silently restarted.
        other_400 = FakeResponse({}, status_code=400)
        other_400.text = '{"code":"validation_error","message":"something else"}'
        session = FakeSession([other_400])

        with pytest.raises(NotionBadRequestError):
            list(_iter_page_ids(cast(requests.Session, session), mock.MagicMock()))

    def test_block_children_inject_page_id(self) -> None:
        session = FakeSession([_list_response([{"id": "b1", "has_children": False}], has_more=False, next_cursor=None)])
        blocks = list(
            _iter_block_children(cast(requests.Session, session), "block-root", "page-42", mock.MagicMock(), 0)
        )

        assert len(blocks) == 1
        assert blocks[0]["_page_id"] == "page-42"

    def test_block_children_recurse_to_depth_limit_and_warn_on_truncation(self) -> None:
        # Every fetched block has children, so recursion would be unbounded without the depth cap. When
        # the cap is reached the truncation must be logged rather than silently dropping deeper blocks —
        # that silent drop was the reported data-loss bug.
        def always_has_children(_index: int) -> FakeResponse:
            return _list_response([{"id": "child", "has_children": True}], has_more=False, next_cursor=None)

        session = FakeSession(always_has_children)
        logger = mock.MagicMock()
        blocks = list(_iter_block_children(cast(requests.Session, session), "block-root", "page-1", logger, 0))

        # depth 0 yields one block, then recurses up to MAX_BLOCK_DEPTH levels.
        assert len(blocks) == MAX_BLOCK_DEPTH + 1
        assert any("exceeds max depth" in str(call.args[0]) for call in logger.warning.call_args_list)

    def test_blocks_stream_resumes_from_saved_queue(self) -> None:
        # On retry the blocks stream must consume the persisted page queue instead of re-running the
        # full page search from scratch — restarting from zero was what burned API quota on retries.
        session = FakeSession([_list_response([{"id": "b1", "has_children": False}], has_more=False, next_cursor=None)])
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = NotionResumeConfig(remaining_page_ids=["p2"])

        tables = list(_blocks_stream(cast(requests.Session, session), mock.MagicMock(), manager))

        assert sum(t.num_rows for t in tables) == 1
        # Only the resumed page's block-children fetch runs; no /v1/search re-enumeration.
        assert len(session.calls) == 1
        assert session.calls[0]["url"].endswith("/v1/blocks/p2/children")

    def test_blocks_stream_saves_progress_after_each_yield(self) -> None:
        # After a batch is flushed the in-progress page must be persisted at the head of the queue, so a
        # crash resumes there. CHUNK_SIZE is patched to 1 to force a yield per block.
        def responses(index: int) -> FakeResponse:
            if index == 0:
                return _list_response([{"id": "p1"}, {"id": "p2"}], has_more=False, next_cursor=None)
            return _list_response([{"id": f"b{index}", "has_children": False}], has_more=False, next_cursor=None)

        session = FakeSession(responses)
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        with mock.patch(f"{MODULE}.CHUNK_SIZE", 1):
            list(_blocks_stream(cast(requests.Session, session), mock.MagicMock(), manager))

        saved = [call.args[0].remaining_page_ids for call in manager.save_state.call_args_list]
        # p1 flushed -> head p1 with p2 queued; p2 flushed -> head p2, nothing left.
        assert saved == [["p1", "p2"], ["p2"]]

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

    def test_request_non_json_2xx_raises_retryable(self) -> None:
        # A 2xx whose body is empty or non-JSON makes response.json() raise JSONDecodeError. That is a
        # truncated/garbled response, not real Notion output, so it must surface as the retryable type
        # carrying the stable phrase get_retryable_errors matches — not crash the sync.
        session = FakeSession(
            [
                FakeResponse(
                    None,
                    status_code=200,
                    json_exc=requests.exceptions.JSONDecodeError("Expecting value: line 1 column 1 (char 0)", "", 0),
                )
            ]
        )
        with pytest.raises(NotionRetryableError) as exc_info:
            cast(Any, _request).__wrapped__(
                cast(requests.Session, session), "GET", "/v1/users", mock.MagicMock(), params={}
            )
        assert "Notion returned a non-JSON response" in str(exc_info.value)

    def test_request_retries_non_json_response(self) -> None:
        # An empty/non-JSON 2xx body is transient like a broken connection: the retry must recover
        # rather than propagate JSONDecodeError as a fatal sync error.
        attempts = {"count": 0}

        def request(*_args: Any, **_kwargs: Any) -> FakeResponse:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return FakeResponse(
                    None,
                    status_code=200,
                    json_exc=requests.exceptions.JSONDecodeError("Expecting value: line 1 column 1 (char 0)", "", 0),
                )
            return FakeResponse({"results": []})

        session = mock.MagicMock()
        session.request.side_effect = request

        with mock.patch(f"{MODULE}._wait_strategy", return_value=0):
            result = _request(cast(requests.Session, session), "GET", "/v1/users", mock.MagicMock(), params={})

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
            valid, message = validate_credentials("tok", NOTION_VERSION_2026_03_11)

        assert valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_validate_credentials_handles_exception(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session", side_effect=requests.ConnectionError("boom")):
            valid, message = validate_credentials("tok", NOTION_VERSION_2026_03_11)

        assert valid is False
        assert message == "boom"

    @parameterized.expand(
        [
            ("title", {"type": "title", "title": [{"plain_text": "Ship "}, {"plain_text": "it"}]}, "Ship it"),
            ("number", {"type": "number", "number": 42}, "42"),
            ("select", {"type": "select", "select": {"name": "Done"}}, "Done"),
            ("empty_select", {"type": "select", "select": None}, None),
            (
                "multi_select",
                {"type": "multi_select", "multi_select": [{"name": "a"}, {"name": "b"}]},
                "a, b",
            ),
            ("checkbox", {"type": "checkbox", "checkbox": False}, "false"),
            (
                "date_range",
                {"type": "date", "date": {"start": "2026-01-01", "end": "2026-01-02"}},
                "2026-01-01 → 2026-01-02",
            ),
            ("date_single", {"type": "date", "date": {"start": "2026-01-01", "end": None}}, "2026-01-01"),
            ("relation", {"type": "relation", "relation": [{"id": "abc"}, {"id": "def"}]}, "abc, def"),
            ("unique_id", {"type": "unique_id", "unique_id": {"prefix": "TASK", "number": 7}}, "TASK-7"),
            (
                "formula_number",
                {"type": "formula", "formula": {"type": "number", "number": 3}},
                "3",
            ),
            (
                "people",
                {"type": "people", "people": [{"object": "user", "id": "u1", "name": "Ada", "type": "person"}]},
                "Ada",
            ),
            (
                "rollup_array",
                {
                    "type": "rollup",
                    "rollup": {
                        "type": "array",
                        "array": [{"type": "number", "number": 1}, {"type": "number", "number": 2}],
                    },
                },
                "1, 2",
            ),
            (
                "files",
                {"type": "files", "files": [{"name": "spec.pdf", "file": {"url": "https://x/spec.pdf"}}]},
                "spec.pdf",
            ),
            ("empty_rich_text", {"type": "rich_text", "rich_text": []}, None),
            # verification carries no name/id, so without its own branch it renders to null on every
            # wiki page. `state` is the actionable field (verified / unverified / expired).
            (
                "verification_verified",
                {
                    "type": "verification",
                    "verification": {
                        "state": "verified",
                        "verified_by": {"id": "u1", "name": "Ada"},
                        "date": {"start": "2026-01-01T00:00:00.000Z"},
                    },
                },
                "verified",
            ),
            (
                "verification_unverified",
                {"type": "verification", "verification": {"state": "unverified", "verified_by": None, "date": None}},
                "unverified",
            ),
            ("not_a_dict", "raw", None),
        ]
    )
    def test_property_to_text_renders_scalar(self, _name: str, prop: Any, expected: str | None) -> None:
        # database_rows shares one table across every database, so each property must reduce to a
        # stable text cell — a regression here reshapes real user columns or breaks the Arrow schema.
        assert _property_to_text(prop) == expected

    def test_flatten_database_row_lifts_properties_and_guards_system_fields(self) -> None:
        page = {
            "id": "page-1",
            "last_edited_time": "2026-01-01T00:00:00Z",
            "url": "https://notion.so/page-1",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task"}]},
                # A property named like a system field must not clobber it.
                "url": {"type": "url", "url": "https://example.com"},
            },
        }
        row = _flatten_database_row(page, "ds-9")

        assert row["id"] == "page-1"
        assert row["_data_source_id"] == "ds-9"
        assert row["Name"] == "Task"
        # The page's own url survives; the colliding property is preserved under a prefixed column.
        assert row["url"] == "https://notion.so/page-1"
        assert row["property_url"] == "https://example.com"
        assert "properties" not in row

    def test_data_source_query_body_incremental_filter(self) -> None:
        # The last_edited_time filter is what unlocks incremental sync; its exact shape is Notion's
        # contract, so lock it in. Without `since` there must be no filter (full refresh).
        assert "filter" not in _data_source_query_body(None, None)
        body = _data_source_query_body("cur", "2026-01-01T00:00:00Z")
        assert body["filter"] == {
            "timestamp": "last_edited_time",
            "last_edited_time": {"on_or_after": "2026-01-01T00:00:00Z"},
        }
        assert body["sorts"] == [{"timestamp": "last_edited_time", "direction": "ascending"}]
        assert body["start_cursor"] == "cur"

    def test_database_rows_stream_queries_each_data_source_and_flattens(self) -> None:
        # Full flow: enumerate data sources via search, then query each and flatten its pages into
        # rows. Guards the wiring from the databases catalog to the row contents that was the gap.
        def responses(index: int) -> FakeResponse:
            if index == 0:  # data_source enumeration
                return _list_response([{"id": "ds-1"}, {"id": "ds-2"}], has_more=False, next_cursor=None)
            page = {"id": f"row-{index}", "properties": {"Name": {"type": "title", "title": [{"plain_text": "x"}]}}}
            return _list_response([page], has_more=False, next_cursor=None)

        session = FakeSession(responses)
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        tables = list(
            _database_rows_stream(
                cast(requests.Session, session),
                mock.MagicMock(),
                manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert sum(t.num_rows for t in tables) == 2
        # One search enumeration plus one query per data source; queries hit the data-source endpoint.
        assert len(session.calls) == 3
        assert session.calls[1]["url"].endswith("/v1/data_sources/ds-1/query")
        assert session.calls[2]["url"].endswith("/v1/data_sources/ds-2/query")

    def test_database_rows_stream_skips_wiki_child_data_sources(self) -> None:
        # A wiki data source returns both pages and child data sources (nested databases). This table
        # is one row per page, and the child data sources already sync through the `databases` stream,
        # so a data_source object must be skipped rather than emitted as a malformed row.
        def responses(index: int) -> FakeResponse:
            if index == 0:
                return _list_response([{"id": "ds-1"}], has_more=False, next_cursor=None)
            return _list_response(
                [
                    {
                        "object": "page",
                        "id": "page-1",
                        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Task"}]}},
                    },
                    {"object": "data_source", "id": "child-db", "title": [{"plain_text": "Nested DB"}], "properties": {}},
                ],
                has_more=False,
                next_cursor=None,
            )

        session = FakeSession(responses)
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        tables = list(
            _database_rows_stream(
                cast(requests.Session, session),
                mock.MagicMock(),
                manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        rows = [row for table in tables for row in table.to_pylist()]
        assert [row["id"] for row in rows] == ["page-1"]

    def test_database_rows_stream_passes_incremental_watermark_to_query(self) -> None:
        # An incremental run must send the last_edited_time filter so Notion returns only changed
        # rows; a regression that drops it silently re-reads the whole database every sync. The
        # watermark reaches a source as a datetime or a string depending on what the pipeline
        # persisted, so both must produce the filter.
        for watermark in (datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC), "2026-01-01T12:00:00Z"):

            def responses(index: int) -> FakeResponse:
                if index == 0:
                    return _list_response([{"id": "ds-1"}], has_more=False, next_cursor=None)
                return _list_response([{"id": "row-1", "properties": {}}], has_more=False, next_cursor=None)

            session = FakeSession(responses)
            manager = mock.MagicMock()
            manager.can_resume.return_value = False

            list(
                _database_rows_stream(
                    cast(requests.Session, session),
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=watermark,
                )
            )

            assert session.calls[1]["json"]["filter"] == {
                "timestamp": "last_edited_time",
                "last_edited_time": {"on_or_after": "2026-01-01T12:00:00Z"},
            }

    def test_database_rows_stream_resumes_from_saved_queue(self) -> None:
        # On retry the stream must consume the persisted data-source queue instead of re-enumerating
        # every data source from scratch — restarting from zero was what burned API quota on retries.
        session = FakeSession([_list_response([{"id": "row-1", "properties": {}}], has_more=False, next_cursor=None)])
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = NotionResumeConfig(remaining_data_source_ids=["ds-2"])

        tables = list(
            _database_rows_stream(
                cast(requests.Session, session),
                mock.MagicMock(),
                manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert sum(t.num_rows for t in tables) == 1
        # Only the resumed data source's query runs; no /v1/search re-enumeration.
        assert len(session.calls) == 1
        assert session.calls[0]["url"].endswith("/v1/data_sources/ds-2/query")

    def test_database_rows_stream_advances_checkpoint_across_empty_data_sources(self) -> None:
        # On an incremental run most data sources return no rows, so the in-loop checkpoint (which
        # only fires on a 2000-row flush) never advances. When the batcher holds nothing pending, the
        # finished source must drop from the resume queue, or a late failure re-queries every earlier
        # source on retry.
        def responses(index: int) -> FakeResponse:
            if index == 0:
                return _list_response([{"id": "ds-1"}, {"id": "ds-2"}, {"id": "ds-3"}], has_more=False, next_cursor=None)
            return _list_response([], has_more=False, next_cursor=None)

        session = FakeSession(responses)
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        list(
            _database_rows_stream(
                cast(requests.Session, session),
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01T00:00:00Z",
            )
        )

        saved = [call.args[0].remaining_data_source_ids for call in manager.save_state.call_args_list]
        assert saved == [["ds-2", "ds-3"], ["ds-3"], []]

    def test_database_rows_stream_keeps_buffered_source_in_checkpoint(self) -> None:
        # A finished data source whose rows are still buffered (below the 2000-row flush) must stay in
        # the queue — advancing past it would drop those unpersisted rows on resume. Here ds-1's one
        # row buffers for the whole run, so the checkpoint never advances.
        def responses(index: int) -> FakeResponse:
            if index == 0:
                return _list_response([{"id": "ds-1"}, {"id": "ds-2"}], has_more=False, next_cursor=None)
            if index == 1:
                return _list_response([{"id": "row-1", "properties": {}}], has_more=False, next_cursor=None)
            return _list_response([], has_more=False, next_cursor=None)

        session = FakeSession(responses)
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        list(
            _database_rows_stream(
                cast(requests.Session, session),
                mock.MagicMock(),
                manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert manager.save_state.call_args_list == []


@pytest.mark.parametrize("endpoint", list(NOTION_ENDPOINTS.keys()))
def test_every_endpoint_has_config(endpoint: str) -> None:
    config = NOTION_ENDPOINTS[endpoint]
    assert config.name == endpoint
    assert config.stream_type in ("search", "users", "blocks", "comments", "database_rows")
    if config.stream_type == "search":
        assert config.object_filter in ("page", "data_source")
    # Only database_rows can filter server-side on last_edited_time, so it is the one incremental stream.
    assert config.supports_incremental is (endpoint == "database_rows")
