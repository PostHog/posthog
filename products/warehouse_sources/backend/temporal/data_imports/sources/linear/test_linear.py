import copy
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from tenacity import Future, RetryCallState

from products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear import (
    LINEAR_MAX_RETRY_AFTER_SECONDS,
    LINEAR_MAX_RETRY_ATTEMPTS,
    LinearResumeConfig,
    LinearRetryableError,
    _make_paginated_request,
    _parse_retry_after,
    _wait_strategy,
    linear_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linear.source import LinearSource


def _make_response(nodes: list[dict[str, Any]], has_next_page: bool, end_cursor: str | None) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {
        "data": {
            "issues": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
            }
        }
    }
    return response


def _make_rate_limited_response(headers: dict[str, str] | None = None) -> MagicMock:
    """Mimic Linear's HTTP-level 429: an HTML body that fails JSON parsing."""
    response = MagicMock()
    response.status_code = 429
    response.ok = False
    response.reason = "Too Many Requests"
    response.text = "<!DOCTYPE html><html><head><title>Rate limited</title></head></html>"
    response.headers = headers or {}
    response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
    return response


def _retry_state(exc: BaseException) -> RetryCallState:
    state = RetryCallState(retry_object=MagicMock(), fn=None, args=(), kwargs={})
    state.outcome = Future.construct(1, exc, has_exception=True)
    return state


def _capture_post_calls(session: MagicMock, responses: list[MagicMock]) -> list[dict[str, Any]]:
    """Configure session.post to record a deep-copied snapshot of variables at each call.

    The paginator mutates a single `variables` dict across pages, so recorded calls all
    reference the same object. Snapshotting here gives us a per-call view for assertions.
    """
    snapshots: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def side_effect(*_args: object, **kwargs: object) -> MagicMock:
        json_payload = kwargs.get("json")
        variables = json_payload.get("variables") if isinstance(json_payload, dict) else None
        snapshots.append(copy.deepcopy(variables) if variables is not None else {})
        return next(response_iter)

    session.post.side_effect = side_effect
    return snapshots


def _make_resumable_manager(*, saved: LinearResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.load_state.return_value = saved
    return manager


# (has_next, end_cursor) per page. Nodes are synthetic; only pagination matters.
PageSpec = tuple[bool, str | None]


class TestMakePaginatedRequest:
    @parameterized.expand(
        [
            # Fresh runs
            ("fresh_multi_page", None, [(True, "c1"), (True, "c2"), (False, None)], None, ["c1", "c2"], False),
            ("fresh_single_empty", None, [(False, None)], None, [], False),
            ("fresh_with_filter", None, [(True, "c1"), (False, None)], "2026-01-01T00:00:00Z", ["c1"], False),
            # Resume runs
            ("resume_final_page_only", "saved-c", [(False, None)], None, [], True),
            ("resume_then_more_pages", "saved-c", [(True, "c1"), (False, None)], None, ["c1"], True),
            (
                "resume_with_filter",
                "saved-c",
                [(True, "c1"), (False, None)],
                "2026-01-01T00:00:00Z",
                ["c1"],
                True,
            ),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_pagination_state(
        self,
        _name: str,
        saved_cursor: str | None,
        page_specs: list[PageSpec],
        filter_gte: str | None,
        expected_save_cursors: list[str],
        first_request_has_cursor: bool,
        mock_session_cls: MagicMock,
    ) -> None:
        session = MagicMock()
        responses = [_make_response([{"id": f"{i}"}], has_next, end) for i, (has_next, end) in enumerate(page_specs)]
        snapshots = _capture_post_calls(session, responses)
        mock_session_cls.return_value = session

        saved_config = LinearResumeConfig(cursor=saved_cursor) if saved_cursor is not None else None
        manager = _make_resumable_manager(saved=saved_config)
        logger = MagicMock()

        list(
            _make_paginated_request(
                access_token="tok",
                endpoint_name="issues",
                logger=logger,
                resumable_source_manager=manager,
                updated_at_gte=filter_gte,
            )
        )

        # Resume path: first request carries the saved cursor; fresh path: no cursor on first request.
        if first_request_has_cursor:
            assert snapshots[0]["cursor"] == saved_cursor
        else:
            assert "cursor" not in snapshots[0]

        # Each non-final page checkpoints the cursor of the next page.
        assert manager.save_state.call_args_list == [((LinearResumeConfig(cursor=c),),) for c in expected_save_cursors]

        # The updated_at filter, if any, must be applied on every page including the resumed first request.
        if filter_gte is not None:
            for variables in snapshots:
                assert variables["filter"] == {"updatedAt": {"gt": filter_gte}}

    @parameterized.expand([("null_end_cursor", None), ("empty_end_cursor", "")])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_raises_when_has_next_page_but_cursor_missing(
        self,
        _name: str,
        bad_cursor: str | None,
        mock_session_cls: MagicMock,
    ) -> None:
        session = MagicMock()
        session.post.side_effect = [_make_response([{"id": "a"}], True, bad_cursor)]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        with pytest.raises(Exception, match="endCursor is empty"):
            list(
                _make_paginated_request(
                    access_token="tok",
                    endpoint_name="issues",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        manager.save_state.assert_not_called()
        assert session.post.call_count == 1

    @patch("time.sleep", return_value=None)
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_http_429_is_retried_then_succeeds(self, mock_session_cls: MagicMock, _mock_sleep: MagicMock) -> None:
        # Linear returns an HTML 429 page that fails JSON parsing. It must be retried with backoff,
        # not surfaced as a non-retryable JSONDecodeError/Exception.
        session = MagicMock()
        session.post.side_effect = [
            _make_rate_limited_response(),
            _make_response([{"id": "a"}], False, None),
        ]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        pages = list(
            _make_paginated_request(
                access_token="tok",
                endpoint_name="issues",
                logger=logger,
                resumable_source_manager=manager,
            )
        )

        assert pages == [[{"id": "a"}]]
        assert session.post.call_count == 2

    @patch("time.sleep", return_value=None)
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_persistent_http_429_raises_retryable_error(
        self, mock_session_cls: MagicMock, _mock_sleep: MagicMock
    ) -> None:
        session = MagicMock()
        session.post.side_effect = [_make_rate_limited_response() for _ in range(LINEAR_MAX_RETRY_ATTEMPTS)]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        with pytest.raises(LinearRetryableError):
            list(
                _make_paginated_request(
                    access_token="tok",
                    endpoint_name="issues",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert session.post.call_count == LINEAR_MAX_RETRY_ATTEMPTS

    @parameterized.expand(
        [
            ("read_timeout", requests.exceptions.ReadTimeout("Read timed out. (read timeout=60)")),
            ("connection_reset", requests.exceptions.ConnectionError("Connection aborted")),
        ]
    )
    @patch("time.sleep", return_value=None)
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_transient_network_error_is_retried_then_succeeds(
        self,
        _name: str,
        transient_exc: Exception,
        mock_session_cls: MagicMock,
        _mock_sleep: MagicMock,
    ) -> None:
        # Linear's POSTs get no transport-level retry, so a transient network error must be folded
        # into the application-level backoff rather than escaping on the first attempt.
        session = MagicMock()
        session.post.side_effect = [transient_exc, _make_response([{"id": "a"}], False, None)]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        pages = list(
            _make_paginated_request(
                access_token="tok",
                endpoint_name="issues",
                logger=logger,
                resumable_source_manager=manager,
            )
        )

        assert pages == [[{"id": "a"}]]
        assert session.post.call_count == 2

    @patch("time.sleep", return_value=None)
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_persistent_network_error_raises_retryable_error(
        self, mock_session_cls: MagicMock, _mock_sleep: MagicMock
    ) -> None:
        session = MagicMock()
        session.post.side_effect = [
            requests.exceptions.ReadTimeout("Read timed out. (read timeout=60)")
            for _ in range(LINEAR_MAX_RETRY_ATTEMPTS)
        ]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        with pytest.raises(LinearRetryableError):
            list(
                _make_paginated_request(
                    access_token="tok",
                    endpoint_name="issues",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert session.post.call_count == LINEAR_MAX_RETRY_ATTEMPTS


class TestRateLimitBackoff:
    @parameterized.expand(
        [
            ("delta_seconds", {"Retry-After": "30"}, 30.0),
            ("zero", {"Retry-After": "0"}, 0.0),
            ("fractional", {"Retry-After": "12.5"}, 12.5),
            ("missing", {}, None),
            ("http_date_unsupported", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
            ("non_numeric", {"Retry-After": "soon"}, None),
        ]
    )
    def test_parse_retry_after(self, _name: str, headers: dict[str, str], expected: float | None) -> None:
        assert _parse_retry_after(_make_rate_limited_response(headers)) == expected

    def test_wait_strategy_honors_retry_after(self) -> None:
        exc = LinearRetryableError("Linear: rate limited (429)", retry_after=45.0)
        assert _wait_strategy(_retry_state(exc)) == 45.0

    def test_wait_strategy_caps_retry_after(self) -> None:
        exc = LinearRetryableError("Linear: rate limited (429)", retry_after=10_000.0)
        assert _wait_strategy(_retry_state(exc)) == LINEAR_MAX_RETRY_AFTER_SECONDS

    def test_wait_strategy_falls_back_to_backoff_without_retry_after(self) -> None:
        exc = LinearRetryableError("Linear: rate limited (429)")
        assert 0 < _wait_strategy(_retry_state(exc)) <= 60

    @patch("time.sleep", return_value=None)
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_429_carries_retry_after_into_exception(self, mock_session_cls: MagicMock, _mock_sleep: MagicMock) -> None:
        # Retry-After of 0 keeps the test fast while still exercising the honored-wait path.
        session = MagicMock()
        session.post.side_effect = [
            _make_rate_limited_response({"Retry-After": "0"}) for _ in range(LINEAR_MAX_RETRY_ATTEMPTS)
        ]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        with pytest.raises(LinearRetryableError) as exc_info:
            list(
                _make_paginated_request(
                    access_token="tok",
                    endpoint_name="issues",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert exc_info.value.retry_after == 0.0
        assert session.post.call_count == LINEAR_MAX_RETRY_ATTEMPTS


class TestLinearSource:
    def test_source_response_wires_primary_key_and_items(self) -> None:
        manager = _make_resumable_manager()
        logger = MagicMock()

        response = linear_source(
            access_token="tok",
            endpoint_name="issues",
            logger=logger,
            resumable_source_manager=manager,
        )

        assert response.name == "issues"
        assert response.primary_keys == ["id"]
        assert callable(response.items)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_get_rows_threads_manager_through(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect = [
            _make_response([{"id": "a"}], True, "cursor-a"),
            _make_response([{"id": "b"}], False, None),
        ]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        response = linear_source(
            access_token="tok",
            endpoint_name="issues",
            logger=logger,
            resumable_source_manager=manager,
        )
        pages = list(cast(Iterable[Any], response.items()))

        assert pages == [[{"id": "a"}], [{"id": "b"}]]
        manager.save_state.assert_called_once_with(LinearResumeConfig(cursor="cursor-a"))


class TestLinearSourceNonRetryableErrors:
    @parameterized.expand(
        [
            # The OAuthMixin raises "Integration not found: <id>" when the linked integration was
            # deleted. The id varies, so matching must rely on the stable prefix.
            ("deleted_integration", "Integration not found: 165665"),
            ("auth_401", "401 Client Error: Unauthorized for url: https://api.linear.app/graphql"),
            ("forbidden_403", "403 Client Error: Forbidden for url: https://api.linear.app/graphql"),
            # NotImplementedError raised by OauthIntegration when the instance lacks Linear client id/secret.
            ("app_not_configured", "Linear app not configured"),
        ]
    )
    def test_non_retryable_errors_match(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = LinearSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("transient_500", "500 Server Error for url: https://api.linear.app/graphql"),
            ("rate_limited", "Linear: rate limited (429)"),
            ("graphql_error", "Linear GraphQL error: Something failed"),
            (
                "read_timeout",
                "Linear: transient network error - HTTPSConnectionPool(host='api.linear.app', port=443): Read timed out. (read timeout=60)",
            ),
        ]
    )
    def test_non_retryable_errors_does_not_match_transient(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = LinearSource().get_non_retryable_errors()
        # Transient/server errors must stay retryable so the pipeline backs off and retries.
        assert not any(key in observed_error for key in non_retryable_errors)
