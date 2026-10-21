from typing import Any, Optional

import pytest
from unittest.mock import MagicMock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frill.frill import (
    FRILL_BASE_URL,
    PAGE_SIZE,
    FrillResumeConfig,
    FrillRetryableError,
    _handle_response,
    _next_cursor,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frill.settings import ENDPOINTS, FRILL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.frill.source import FrillSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frill import FrillSourceConfig


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


def _driver(api_key: str = "k") -> SourceDriver:
    return SourceDriver(FrillSource(), FrillSourceConfig(api_key=api_key))


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


class TestNextCursor:
    def test_has_next_page_false_returns_none(self) -> None:
        data = _page([{"idx": "1"}], has_next=True, end_cursor="cur")
        data["pagination"]["hasNextPage"] = False
        assert _next_cursor(data, data["data"], None) is None

    @pytest.mark.parametrize("body", [{}, {"pagination": None}, {"pagination": {"hasNextPage": True}}])
    def test_missing_pagination_or_cursor_returns_none(self, body: dict[str, Any]) -> None:
        assert _next_cursor(body, [{"idx": "1"}], None) is None

    def test_after_shape_short_page_returns_none(self) -> None:
        records = [{"idx": "1"}]
        data: dict[str, Any] = {"data": records, "pagination": {"total": 1, "after": "cur"}}
        assert _next_cursor(data, records, None) is None


class TestGetRows:
    def test_paginates_until_has_next_false_and_saves_after_each_page(self) -> None:
        responses = [
            ScriptedResponse(json=_page([{"idx": "idea_1"}], has_next=True, end_cursor="c1")),
            ScriptedResponse(json=_page([{"idx": "idea_2"}], has_next=True, end_cursor="c2")),
            ScriptedResponse(json=_page([{"idx": "idea_3"}], has_next=False)),
        ]

        result = _driver().run("ideas", responses)

        assert result.raised is None
        assert result.params("after") == [None, "c1", "c2"]
        assert result.params("limit") == [str(PAGE_SIZE)] * 3
        assert result.items == [[{"idx": "idea_1"}], [{"idx": "idea_2"}], [{"idx": "idea_3"}]]
        # State is saved after each non-terminal page so a crash re-yields rather than skips.
        assert result.saved_states == [FrillResumeConfig(after="c1"), FrillResumeConfig(after="c2")]

    def test_session_carries_bearer_auth_redacts_key_and_disables_capture(self) -> None:
        result = _driver("secret").run("ideas", [ScriptedResponse(json=_page([], has_next=False))])

        assert result.raised is None
        assert result.requests[0].headers["authorization"] == "Bearer secret"
        assert result.session_options[0]["headers"]["Authorization"] == "Bearer secret"
        assert result.session_options[0]["redact_values"] == ("secret",)
        # Frill responses carry user-authored feedback/notes the scrubber can't anonymize, so
        # sample capture must stay off to keep that content out of the shared HTTP sample store.
        assert result.session_options[0]["capture"] is False


class TestCommentsFanOut:
    def test_fans_out_over_ideas_and_injects_parent_idx(self) -> None:
        ideas: list[dict[str, Any]] = [
            {"idx": "idea_a", "comment_count": 2, "note_count": 0},
            # Both counts explicitly zero — the per-idea request is skipped.
            {"idx": "idea_b", "comment_count": 0, "note_count": 0},
            # Counts missing — fetched anyway, to stay conservative.
            {"idx": "idea_c"},
        ]
        responses = [
            ScriptedResponse(json=_page(ideas, has_next=False)),
            ScriptedResponse(json=_page([{"idx": "comment_1"}, {"idx": "comment_2"}], has_next=False)),
            ScriptedResponse(json=_page([], has_next=False)),
        ]

        result = _driver().run("comments", responses)

        assert result.raised is None
        assert result.urls[0] == f"{FRILL_BASE_URL}/ideas?limit={PAGE_SIZE}"
        comment_requests = [request for request in result.requests if request.path.endswith("/comments")]
        assert [request.param("idea_idx") for request in comment_requests] == ["idea_a", "idea_c"]
        assert all(request.param("included_types") == "comments,notes" for request in comment_requests)
        assert result.items == [
            [{"idx": "comment_1", "_idea_idx": "idea_a"}, {"idx": "comment_2", "_idea_idx": "idea_a"}]
        ]
        # The single ideas page was terminal, so there is nothing to resume to.
        assert result.saved_states == []

    def test_saves_ideas_cursor_after_full_page_of_comments(self) -> None:
        responses = [
            ScriptedResponse(
                json=_page(
                    [{"idx": "idea_a", "comment_count": 1, "note_count": 0}], has_next=True, end_cursor="ideas-c1"
                )
            ),
            ScriptedResponse(json=_page([{"idx": "comment_1"}], has_next=False)),
            ScriptedResponse(json=_page([{"idx": "idea_b", "comment_count": 0, "note_count": 0}], has_next=False)),
        ]

        result = _driver().run("comments", responses)

        assert result.raised is None
        assert result.items == [[{"idx": "comment_1", "_idea_idx": "idea_a"}]]
        assert result.saved_states == [FrillResumeConfig(after="ideas-c1")]

    def test_resume_seeds_ideas_cursor(self) -> None:
        result = _driver().run(
            "comments",
            [ScriptedResponse(json=_page([], has_next=False))],
            resume_state=FrillResumeConfig(after="ideas-resume"),
        )

        assert result.raised is None
        assert result.requests[0].path == "/v1/ideas"
        assert result.requests[0].param("after") == "ideas-resume"


class TestFrillSource:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=_page([], has_next=False))])

        config = FRILL_ENDPOINTS[endpoint]
        assert result.raised is None
        response = result.response
        assert response is not None
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


class TestValidateCredentials:
    def test_error_body_is_invalid(self) -> None:
        with scripted_network([ScriptedResponse(json={"error": True, "message": "bad key"})]):
            assert validate_credentials("k") is False

    def test_non_json_body_is_invalid(self) -> None:
        with scripted_network([ScriptedResponse(body=b"not json")]):
            assert validate_credentials("k") is False
