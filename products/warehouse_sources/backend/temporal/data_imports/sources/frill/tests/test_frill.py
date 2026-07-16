from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.frill.frill import (
    FRILL_BASE_URL,
    PAGE_SIZE,
    FrillResumeConfig,
    FrillRetryableError,
    _handle_response,
    _next_cursor,
    frill_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frill.settings import ENDPOINTS, FRILL_ENDPOINTS


def _resp(body: Any, status: int = 200) -> Any:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 400
    response.json.return_value = body
    response.text = str(body)
    return response


def _page(
    records: list[dict[str, Any]],
    has_next: Optional[bool] = None,
    end_cursor: Optional[str] = None,
) -> dict[str, Any]:
    pagination: dict[str, Any] = {"total": len(records)}
    if has_next is not None:
        pagination["hasNextPage"] = has_next
    if end_cursor is not None:
        pagination["endCursor"] = end_cursor
    return {"data": records, "pagination": pagination, "meta": {}}


def _manager(resume: FrillResumeConfig | None = None) -> Any:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _drive(
    endpoint: str, manager: Any, responses: list[Any]
) -> tuple[list[tuple[str, dict[str, Any]]], list[list[dict[str, Any]]]]:
    """Drive ``get_rows`` with a mocked tracked session, returning (requests, yielded_batches)."""
    calls: list[tuple[str, dict[str, Any]]] = []
    response_iter = iter(responses)

    def fake_get(url: str, params: Any = None, timeout: Any = None, **_kwargs: Any) -> Any:
        calls.append((url, dict(params or {})))
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.frill.frill.make_tracked_session"
    ) as MockSession:
        MockSession.return_value.get.side_effect = fake_get
        batches = list(get_rows(api_key="k", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=manager))

    return calls, batches


class TestHandleResponse:
    # Exercise the per-response classification directly, so a single attempt's behaviour can be
    # asserted without driving the tenacity retry loop (and its real backoff sleeps).
    def _handle(self, response: Any) -> dict[str, Any]:
        return _handle_response(response, f"{FRILL_BASE_URL}/ideas", MagicMock())

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        with pytest.raises(FrillRetryableError):
            self._handle(_resp({}, status=status))

    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_client_errors_raise_http_error(self, status: int) -> None:
        response = _resp({}, status=status)
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=response)
        with pytest.raises(requests.HTTPError):
            self._handle(response)

    def test_error_body_on_200_raises_http_error(self) -> None:
        with pytest.raises(requests.HTTPError, match="provide a valid api_key"):
            self._handle(_resp({"error": True, "message": "Unauthorized - please provide a valid api_key"}))

    def test_non_dict_body_raises_http_error(self) -> None:
        with pytest.raises(requests.HTTPError, match="unexpected body"):
            self._handle(_resp([{"idx": "idea_1"}]))

    def test_success_returns_body(self) -> None:
        body = _page([{"idx": "idea_1"}], has_next=False)
        assert self._handle(_resp(body)) == body


class TestNextCursor:
    def test_has_next_page_true_returns_cursor(self) -> None:
        data = _page([{"idx": "1"}], has_next=True, end_cursor="cur")
        assert _next_cursor(data, data["data"], None) == "cur"

    def test_has_next_page_false_returns_none(self) -> None:
        data = _page([{"idx": "1"}], has_next=True, end_cursor="cur")
        data["pagination"]["hasNextPage"] = False
        assert _next_cursor(data, data["data"], None) is None

    @pytest.mark.parametrize("body", [{}, {"pagination": None}, {"pagination": {"hasNextPage": True}}])
    def test_missing_pagination_or_cursor_returns_none(self, body: dict[str, Any]) -> None:
        assert _next_cursor(body, [{"idx": "1"}], None) is None

    def test_repeated_cursor_returns_none(self) -> None:
        # Guards against an infinite loop if the API keeps echoing the same cursor.
        data = _page([{"idx": "1"}], has_next=True, end_cursor="cur")
        assert _next_cursor(data, data["data"], "cur") is None

    def test_after_shape_full_page_returns_cursor(self) -> None:
        # The embedded OpenAPI specs describe pagination as {total, before, after} with no
        # hasNextPage flag; a full page means there may be more results.
        records = [{"idx": str(i)} for i in range(PAGE_SIZE)]
        data = {"data": records, "pagination": {"total": 500, "after": "cur"}}
        assert _next_cursor(data, records, None) == "cur"

    def test_after_shape_short_page_returns_none(self) -> None:
        records = [{"idx": "1"}]
        data: dict[str, Any] = {"data": records, "pagination": {"total": 1, "after": "cur"}}
        assert _next_cursor(data, records, None) is None


class TestGetRows:
    def test_paginates_until_has_next_false_and_saves_after_each_page(self) -> None:
        manager = _manager()
        responses = [
            _resp(_page([{"idx": "idea_1"}], has_next=True, end_cursor="c1")),
            _resp(_page([{"idx": "idea_2"}], has_next=True, end_cursor="c2")),
            _resp(_page([{"idx": "idea_3"}], has_next=False)),
        ]

        calls, batches = _drive("ideas", manager, responses)

        assert [params.get("after") for _, params in calls] == [None, "c1", "c2"]
        assert all(params.get("limit") == PAGE_SIZE for _, params in calls)
        assert batches == [[{"idx": "idea_1"}], [{"idx": "idea_2"}], [{"idx": "idea_3"}]]
        # State is saved after each non-terminal page so a crash re-yields rather than skips.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [FrillResumeConfig(after="c1"), FrillResumeConfig(after="c2")]

    def test_resume_seeds_cursor_from_saved_state(self) -> None:
        manager = _manager(FrillResumeConfig(after="resume-cursor"))

        calls, batches = _drive("votes", manager, [_resp(_page([{"idx": "vote_1"}], has_next=False))])

        assert calls[0][1].get("after") == "resume-cursor"
        manager.load_state.assert_called_once()
        assert len(batches) == 1

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = _manager()

        _, batches = _drive("statuses", manager, [_resp(_page([{"idx": "status_1"}], has_next=False))])

        assert len(batches) == 1
        manager.save_state.assert_not_called()

    def test_empty_page_yields_nothing(self) -> None:
        manager = _manager()

        _, batches = _drive("ideas", manager, [_resp(_page([], has_next=False))])

        assert batches == []
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize(
        ("endpoint", "param", "value"),
        [
            ("followers", "include_attributes", "true"),
        ],
    )
    def test_endpoint_extra_params_are_sent(self, endpoint: str, param: str, value: str) -> None:
        manager = _manager()

        calls, _ = _drive(endpoint, manager, [_resp(_page([{"idx": "x"}], has_next=False))])

        assert calls[0][0] == f"{FRILL_BASE_URL}{FRILL_ENDPOINTS[endpoint].path}"
        assert calls[0][1].get(param) == value

    def test_session_carries_bearer_auth_redacts_key_and_disables_capture(self) -> None:
        manager = _manager()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.frill.frill.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _resp(_page([], has_next=False))
            list(get_rows(api_key="secret", endpoint="ideas", logger=MagicMock(), resumable_source_manager=manager))

        _, kwargs = MockSession.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer secret"
        assert kwargs["redact_values"] == ("secret",)
        # Frill responses carry user-authored feedback/notes the scrubber can't anonymize, so
        # sample capture must stay off to keep that content out of the shared HTTP sample store.
        assert kwargs["capture"] is False


class TestCommentsFanOut:
    def test_fans_out_over_ideas_and_injects_parent_idx(self) -> None:
        manager = _manager()
        ideas: list[dict[str, Any]] = [
            {"idx": "idea_a", "comment_count": 2, "note_count": 0},
            # Both counts explicitly zero — the per-idea request is skipped.
            {"idx": "idea_b", "comment_count": 0, "note_count": 0},
            # Counts missing — fetched anyway, to stay conservative.
            {"idx": "idea_c"},
        ]
        responses = [
            _resp(_page(ideas, has_next=False)),
            _resp(_page([{"idx": "comment_1"}, {"idx": "comment_2"}], has_next=False)),
            _resp(_page([], has_next=False)),
        ]

        calls, batches = _drive("comments", manager, responses)

        assert calls[0][0] == f"{FRILL_BASE_URL}/ideas"
        comment_calls = [(url, params) for url, params in calls if url.endswith("/comments")]
        assert [params.get("idea_idx") for _, params in comment_calls] == ["idea_a", "idea_c"]
        assert all(params.get("included_types") == "comments,notes" for _, params in comment_calls)
        assert batches == [[{"idx": "comment_1", "_idea_idx": "idea_a"}, {"idx": "comment_2", "_idea_idx": "idea_a"}]]
        # The single ideas page was terminal, so there is nothing to resume to.
        manager.save_state.assert_not_called()

    def test_saves_ideas_cursor_after_full_page_of_comments(self) -> None:
        manager = _manager()
        responses = [
            _resp(
                _page([{"idx": "idea_a", "comment_count": 1, "note_count": 0}], has_next=True, end_cursor="ideas-c1")
            ),
            _resp(_page([{"idx": "comment_1"}], has_next=False)),
            _resp(_page([{"idx": "idea_b", "comment_count": 0, "note_count": 0}], has_next=False)),
        ]

        _, batches = _drive("comments", manager, responses)

        assert batches == [[{"idx": "comment_1", "_idea_idx": "idea_a"}]]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [FrillResumeConfig(after="ideas-c1")]

    def test_resume_seeds_ideas_cursor(self) -> None:
        manager = _manager(FrillResumeConfig(after="ideas-resume"))

        calls, _ = _drive("comments", manager, [_resp(_page([], has_next=False))])

        assert calls[0][0] == f"{FRILL_BASE_URL}/ideas"
        assert calls[0][1].get("after") == "ideas-resume"


class TestFrillSource:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_response_shape(self, endpoint: str) -> None:
        response = frill_source(
            api_key="k", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )

        config = FRILL_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_comments_primary_key_includes_parent(self) -> None:
        # Fan-out child rows must be unique table-wide, not per parent.
        assert FRILL_ENDPOINTS["comments"].primary_keys == ["_idea_idx", "idx"]

    @pytest.mark.parametrize("endpoint", ["statuses", "topics"])
    def test_endpoints_without_timestamps_are_unpartitioned(self, endpoint: str) -> None:
        assert FRILL_ENDPOINTS[endpoint].partition_key is None


class TestValidateCredentials:
    def _validate(self, response: Any = None, raises: Exception | None = None) -> bool:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.frill.frill.make_tracked_session"
        ) as MockSession:
            get = MockSession.return_value.get
            if raises is not None:
                get.side_effect = raises
            else:
                get.return_value = response
            return validate_credentials("k")

    def test_valid_key(self) -> None:
        assert self._validate(_resp(_page([{"idx": "status_1"}], has_next=False))) is True

    def test_unauthorized_is_invalid(self) -> None:
        assert self._validate(_resp({"success": False, "message": "Unauthorized"}, status=401)) is False

    def test_error_body_is_invalid(self) -> None:
        assert self._validate(_resp({"error": True, "message": "bad key"})) is False

    def test_network_error_is_invalid(self) -> None:
        assert self._validate(raises=requests.ConnectionError("boom")) is False

    def test_non_json_body_is_invalid(self) -> None:
        response = _resp({})
        response.json.side_effect = ValueError("not json")
        assert self._validate(response) is False
