from collections.abc import Callable
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from tenacity import RetryCallState

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.notion import NotionSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion import (
    ADMIN_TOKEN_FORBIDDEN_ERROR,
    ADMIN_TOKEN_INVALID_ERROR,
    ADMIN_TOKEN_MISSING_ERROR,
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
    _get_headers,
    _iter_block_children,
    _iter_page_ids,
    _parse_retry_after,
    _request,
    _search_body,
    _wait_strategy,
    check_permission_groups_access,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.source import NotionSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.notion.notion"


def _fresh_manager() -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = False
    return manager


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


def _scripted_list(
    results: list[dict[str, Any]], has_more: bool = False, next_cursor: str | None = None
) -> ScriptedResponse:
    return ScriptedResponse(json={"results": results, "has_more": has_more, "next_cursor": next_cursor})


class _FakeRetryState:
    """Minimal RetryCallState stand-in carrying just the failing outcome."""

    def __init__(self, exception: BaseException) -> None:
        self.outcome = mock.MagicMock()
        self.outcome.exception.return_value = exception


class TestNotion:
    @staticmethod
    def _driver(admin_token: str | None = None) -> SourceDriver:
        return SourceDriver(NotionSource(), NotionSourceConfig(api_key="tok", admin_api_key=admin_token))

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

    def test_search_stream_paginates_and_terminates(self) -> None:
        result = self._driver().run(
            "pages",
            [
                _scripted_list([{"id": "p1"}], has_more=True, next_cursor="c1"),
                _scripted_list([{"id": "p2"}]),
            ],
        )

        assert result.raised is None
        assert sum(t.num_rows for t in result.items) == 2
        # Two pages fetched, then the loop terminates on has_more=False.
        assert result.paths == ["/v1/search", "/v1/search"]

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
        result = self._driver().run(
            "pages",
            [
                ScriptedResponse(status=400, body=self._invalid_cursor_response().text.encode()),
                _scripted_list([{"id": "p1"}]),
            ],
            resume_state=NotionResumeConfig(next_cursor="stale-cursor"),
        )

        assert result.raised is None
        assert sum(t.num_rows for t in result.items) == 1
        # First request replays the stale cursor (rejected); the restart carries no cursor.
        assert result.requests[0].json()["start_cursor"] == "stale-cursor"
        assert "start_cursor" not in result.requests[1].json()

    def test_search_stream_propagates_non_cursor_bad_request(self) -> None:
        # A 400 that is not the invalid-cursor case is a genuine bad request and must still fail the
        # sync rather than being silently restarted.
        result = self._driver().run(
            "pages",
            [ScriptedResponse(status=400, json={"code": "validation_error", "message": "something else"})],
            resume_state=NotionResumeConfig(next_cursor="stale-cursor"),
        )

        assert isinstance(result.raised, NotionBadRequestError)
        assert result.requests[0].json()["start_cursor"] == "stale-cursor"
        assert len(result.requests) == 1

    def test_users_stream_restarts_when_resumed_cursor_invalid(self) -> None:
        # The users stream persists the same kind of resume cursor as search, so a stale cursor must
        # trigger the same restart-from-the-beginning recovery rather than crashing the sync.
        result = self._driver().run(
            "users",
            [
                ScriptedResponse(status=400, body=self._invalid_cursor_response().text.encode()),
                _scripted_list([{"id": "u1"}]),
            ],
            resume_state=NotionResumeConfig(next_cursor="stale-cursor"),
        )

        assert result.raised is None
        assert sum(t.num_rows for t in result.items) == 1
        assert result.params("start_cursor") == ["stale-cursor", None]

    def test_users_stream_stages_next_cursor_before_yielding_a_finished_page(self) -> None:
        with mock.patch(f"{MODULE}.CHUNK_SIZE", 1):
            result = self._driver().run(
                "users",
                [
                    _scripted_list([{"id": "u1"}, {"id": "u2"}], has_more=True, next_cursor="c1"),
                    _scripted_list([{"id": "u3"}]),
                ],
            )

        assert result.raised is None
        assert [t.num_rows for t in result.items] == [2, 1]
        assert result.saved_states == [NotionResumeConfig(next_cursor="c1")]

    def test_permission_groups_stream_pages_through_the_workspace_groups(self) -> None:
        result = self._driver("adm").run(
            "permission_groups",
            [
                ScriptedResponse(json={"object": "user", "bot": {"workspace_id": "ws-1"}}),
                _scripted_list([{"object": "group", "id": "g1", "name": "Eng"}], True, "c1"),
                _scripted_list([{"object": "group", "id": "g2", "name": "Ops"}]),
            ],
        )

        assert result.raised is None
        assert sum(t.num_rows for t in result.items) == 2
        assert result.paths == [
            "/v1/users/me",
            "/admin/v1/spaces/ws-1/groups",
            "/admin/v1/spaces/ws-1/groups",
        ]
        assert result.params("start_cursor") == [None, None, "c1"]

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

    @parameterized.expand(
        [
            ("blocks", _blocks_stream, "/v1/blocks/p2/children"),
            ("comments", _comments_stream, "/v1/comments"),
        ]
    )
    def test_page_fan_out_resumes_from_saved_queue(self, _name, _stream, expected_path) -> None:
        # On retry the fan-out must consume the persisted page queue instead of re-running the
        # full page search from scratch — restarting from zero was what burned API quota on retries.
        result = self._driver().run(
            _name,
            [_scripted_list([{"id": "b1", "has_children": False}])],
            resume_state=NotionResumeConfig(remaining_page_ids=["p2"]),
        )

        assert result.raised is None
        assert sum(t.num_rows for t in result.items) == 1
        # Only the resumed page's fetch runs; no /v1/search re-enumeration.
        assert result.paths == [expected_path]

    @parameterized.expand([("blocks", _blocks_stream), ("comments", _comments_stream)])
    def test_pages_without_rows_move_the_queue_and_reach_safe_points(self, _name, _stream) -> None:
        with mock.patch(f"{MODULE}.EMPTY_PAGE_STAGE_INTERVAL_SECONDS", 0):
            result = self._driver().run(
                _name,
                [
                    _scripted_list([{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]),
                    *[_scripted_list([]) for _ in range(3)],
                ],
            )

        assert result.raised is None
        assert result.items == []
        assert [state.remaining_page_ids for state in result.saved_states] == [["p2", "p3"], ["p3"], []]
        assert [state.remaining_page_ids for state in result.committed_states] == [["p2", "p3"], ["p3"], []]

    def test_a_sparse_page_run_yields_a_partial_chunk_with_its_queue_staged_first(self) -> None:
        def responses(index: int) -> FakeResponse:
            if index == 0:
                return _list_response([{"id": "p1"}, {"id": "p2"}], has_more=False, next_cursor=None)
            return _list_response([{"id": f"cm{index}"}], has_more=False, next_cursor=None)

        session = FakeSession(responses)
        manager = _fresh_manager()
        events: list[Any] = []
        manager.save_state.side_effect = lambda state: events.append(state.remaining_page_ids)

        with mock.patch(f"{MODULE}.PARTIAL_FLUSH_INTERVAL_SECONDS", 0):
            for table in _comments_stream(cast(requests.Session, session), mock.MagicMock(), manager):
                events.append(table.num_rows)

        assert events == [["p2"], 1, [], 1]
        manager.safe_point.assert_not_called()

    def test_blocks_stream_saves_progress_after_each_yield(self) -> None:
        # After a batch is flushed the in-progress page must be persisted at the head of the queue, so a
        # crash resumes there. CHUNK_SIZE is patched to 1 to force a yield per block.
        with mock.patch(f"{MODULE}.CHUNK_SIZE", 1):
            result = self._driver().run(
                "blocks",
                [
                    _scripted_list([{"id": "p1"}, {"id": "p2"}]),
                    _scripted_list([{"id": "b1", "has_children": False}]),
                    _scripted_list([{"id": "b2", "has_children": False}]),
                ],
            )

        assert result.raised is None
        saved = [state.remaining_page_ids for state in result.saved_states]
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
        logger = mock.MagicMock()
        result = self._driver().run(
            "comments",
            [
                _scripted_list([{"id": "p1"}, {"id": "p2"}]),
                ScriptedResponse(status=400, json={}),  # comments for p1 -> rejected
                _scripted_list([{"id": "cm"}]),  # comments for p2
            ],
            logger=logger,
        )

        assert result.raised is None
        total_rows = sum(t.num_rows for t in result.items)
        assert total_rows == 1
        assert logger.warning.called
        assert result.paths == ["/v1/search", "/v1/comments", "/v1/comments"]

    def test_comments_stream_skips_missing_page(self) -> None:
        # One page is deleted/unshared between search and the comments fetch (404). That page must be
        # skipped without crashing the sync; comments for the surviving page still come through.
        logger = mock.MagicMock()
        result = self._driver().run(
            "comments",
            [
                _scripted_list([{"id": "p1"}, {"id": "p2"}]),
                ScriptedResponse(status=404, json={}),  # comments for p1 -> gone
                _scripted_list([{"id": "cm"}]),  # comments for p2
            ],
            logger=logger,
        )

        assert result.raised is None
        total_rows = sum(t.num_rows for t in result.items)
        assert total_rows == 1
        assert logger.warning.called
        # search + comments(p1, 404) + comments(p2)
        assert result.paths == ["/v1/search", "/v1/comments", "/v1/comments"]

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

    def test_wait_strategy_caps_retry_after(self) -> None:
        state = _FakeRetryState(NotionRetryableError("rate limited", retry_after=10_000.0))
        assert _wait_strategy(cast(RetryCallState, state)) == MAX_RETRY_AFTER_SECONDS

    def test_comments_stream_respects_page_cap(self) -> None:
        # First call is the page search (one page, then done); every subsequent /v1/comments
        # call reports another page, so the per-parent cap must stop the scan.
        responses = [_scripted_list([{"id": "p1"}])]
        responses.extend(_scripted_list([{"id": "cm"}], True, "next") for _ in range(MAX_CHILD_PAGES_PER_PARENT))
        logger = mock.MagicMock()
        result = self._driver().run("comments", responses, logger=logger)

        # One search call plus the capped number of comment-page fetches.
        assert result.raised is None
        assert len(result.requests) == 1 + MAX_CHILD_PAGES_PER_PARENT
        assert logger.warning.called

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Create a new internal integration token"),
            (403, False, "Give it read capabilities"),
            (500, False, "Wait a few minutes"),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_next_step: str | None
    ) -> None:
        # Every refusal has to name a next step: the wizard shows this string and nothing else.
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            valid, message = validate_credentials("tok", NOTION_VERSION_2026_03_11)

        assert valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/v1/users/me"}
        if expected_valid:
            assert message is None
        else:
            assert expected_next_step is not None
            assert expected_next_step in (message or "")
            assert str(status_code) not in (message or "")

    def test_validate_credentials_handles_exception(self) -> None:
        # A connection error repr names the host and the urllib3 internals, none of which the
        # person filling in the token field can act on.
        with scripted_network(
            always(ConnectionError("HTTPSConnectionPool(host='api.notion.com', port=443)"))
        ) as network:
            valid, message = validate_credentials("tok", NOTION_VERSION_2026_03_11)

        assert valid is False
        assert "Wait a few minutes" in (message or "")
        assert "HTTPSConnectionPool" not in (message or "")
        assert {request.path for request in network.requests_log} == {"/v1/users/me"}

    @parameterized.expand(
        [
            ("no_admin_token", None, 200, None, ADMIN_TOKEN_MISSING_ERROR),
            ("integration_token_rejected", "adm", 401, None, None),
            ("admin_token_rejected", "adm", 200, 401, ADMIN_TOKEN_INVALID_ERROR),
            ("admin_scope_missing", "adm", 200, 403, ADMIN_TOKEN_FORBIDDEN_ERROR),
            ("reachable", "adm", 200, 200, None),
            ("rate_limited_is_not_a_denial", "adm", 200, 429, None),
        ]
    )
    def test_check_permission_groups_access(
        self,
        _name: str,
        admin_token: str | None,
        me_status: int,
        admin_status: int | None,
        expected: str | None,
    ) -> None:
        responses = [ScriptedResponse(status=me_status, json={"bot": {"workspace_id": "ws-1"}})]
        if admin_status is not None:
            responses.extend(
                ScriptedResponse(status=admin_status, json={"results": []})
                for _ in range(4 if admin_status == 429 else 1)
            )
        with scripted_network(responses) as network:
            message = check_permission_groups_access("tok", admin_token, NOTION_VERSION_2026_03_11)

        assert message == expected
        expected_admin_urls = (
            ["https://api.notion.com/admin/v1/spaces/ws-1/groups?page_size=1"] if admin_status is not None else []
        )
        admin_urls = [request.url for request in network.requests_log if request.path.startswith("/admin/")]
        if admin_status == 429:
            assert set(admin_urls) == set(expected_admin_urls)
        else:
            assert admin_urls == expected_admin_urls
