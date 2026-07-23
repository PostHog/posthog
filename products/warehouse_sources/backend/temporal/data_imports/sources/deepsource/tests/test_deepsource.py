import copy
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.deepsource import (
    DEEPSOURCE_MAX_RETRY_ATTEMPTS,
    DeepsourceResumeConfig,
    DeepsourceRetryableError,
    _fan_out_connection_rows,
    _metric_rows,
    _per_repository_object_rows,
    _report_rows,
    _repositories_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.source import DeepsourceSource

_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.deepsource.make_tracked_session"
)


def _connection_response(
    parent_field: str,
    connection_field: str,
    nodes: list[dict[str, Any]],
    has_next_page: bool,
    end_cursor: str | None,
    parent_extra: dict[str, Any] | None = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {
        "data": {
            parent_field: {
                **(parent_extra or {}),
                connection_field: {
                    "edges": [{"node": node} for node in nodes],
                    "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
                },
            }
        }
    }
    return response


def _null_parent_response(parent_field: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {"data": {parent_field: None}}
    return response


def _error_response(status_code: int, reason: str, body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = False
    response.reason = reason
    response.headers = {}
    if body is not None:
        response.json.return_value = body
    else:
        response.json.side_effect = ValueError("no body")
    return response


def _repo_names_response(repos: list[tuple[str, bool]]) -> MagicMock:
    return _connection_response(
        "account",
        "repositories",
        [{"name": name, "isActivated": activated} for name, activated in repos],
        False,
        None,
    )


def _capture_post_calls(session: MagicMock, responses: list[MagicMock]) -> list[dict[str, Any]]:
    """session.post records a deep-copied snapshot of GraphQL variables per call."""
    snapshots: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def side_effect(*_args: object, **kwargs: object) -> MagicMock:
        json_payload = kwargs.get("json")
        variables = json_payload.get("variables") if isinstance(json_payload, dict) else None
        snapshots.append(copy.deepcopy(variables) if variables is not None else {})
        return next(response_iter)

    session.post.side_effect = side_effect
    return snapshots


def _make_manager(saved: DeepsourceResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = saved is not None
    manager.load_state.return_value = saved
    return manager


class TestRepositoriesPagination:
    @parameterized.expand(
        [
            # (name, saved_cursor, page specs (has_next, end_cursor), expected checkpoint cursors, first request cursor)
            ("fresh_multi_page", None, [(True, "c1"), (True, "c2"), (False, None)], ["c1", "c2"], None),
            ("fresh_single_page", None, [(False, None)], [], None),
            ("resume_then_more_pages", "saved-c", [(True, "c1"), (False, None)], ["c1"], "saved-c"),
        ]
    )
    def test_pagination_and_checkpoints(
        self,
        _name: str,
        saved_cursor: str | None,
        page_specs: list[tuple[bool, str | None]],
        expected_checkpoints: list[str],
        first_request_cursor: str | None,
    ) -> None:
        session = MagicMock()
        responses = [
            _connection_response("account", "repositories", [{"id": f"repo-{i}", "name": f"repo-{i}"}], has_next, end)
            for i, (has_next, end) in enumerate(page_specs)
        ]
        snapshots = _capture_post_calls(session, responses)

        saved = DeepsourceResumeConfig(cursor=saved_cursor) if saved_cursor else None
        manager = _make_manager(saved)

        pages = list(_repositories_rows(session, "acme", "GITHUB", MagicMock(), manager))

        assert [row["id"] for page in pages for row in page] == [f"repo-{i}" for i in range(len(page_specs))]
        assert snapshots[0]["cursor"] == first_request_cursor
        assert manager.save_state.call_args_list == [
            ((DeepsourceResumeConfig(cursor=c),),) for c in expected_checkpoints
        ]

    def test_raises_when_has_next_page_but_cursor_missing(self) -> None:
        session = MagicMock()
        session.post.side_effect = [_connection_response("account", "repositories", [{"id": "a"}], True, None)]

        with pytest.raises(Exception, match="endCursor is empty"):
            list(_repositories_rows(session, "acme", "GITHUB", MagicMock(), _make_manager()))

    def test_missing_account_raises_actionable_error(self) -> None:
        session = MagicMock()
        session.post.side_effect = [_null_parent_response("account")]

        with pytest.raises(Exception, match="DeepSource account not found"):
            list(_repositories_rows(session, "acme", "GITHUB", MagicMock(), _make_manager()))


class TestFanOut:
    def test_fan_out_skips_completed_and_unactivated_and_resumes_cursor(self) -> None:
        session = MagicMock()
        responses = [
            # Repository enumeration: alpha already completed, beta not activated, gamma resumes.
            _repo_names_response([("alpha", True), ("beta", False), ("gamma", True)]),
            _connection_response(
                "repository",
                "analysisRuns",
                [{"id": "run-1", "createdAt": "2026-01-01T00:00:00Z"}],
                False,
                None,
                parent_extra={"id": "RID-gamma", "name": "gamma"},
            ),
        ]
        snapshots = _capture_post_calls(session, responses)

        saved = DeepsourceResumeConfig(
            completed_repositories=["alpha"], current_repository="gamma", cursor="saved-inner"
        )
        manager = _make_manager(saved)

        pages = list(_fan_out_connection_rows(session, "acme", "GITHUB", "analysis_runs", MagicMock(), manager))

        # Only gamma is walked, resuming from the saved inner cursor.
        assert session.post.call_count == 2
        assert snapshots[1]["name"] == "gamma"
        assert snapshots[1]["cursor"] == "saved-inner"
        # Rows carry the repository context needed downstream.
        assert pages == [
            [
                {
                    "id": "run-1",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "repositoryId": "RID-gamma",
                    "repositoryName": "gamma",
                }
            ]
        ]
        # Finishing gamma checkpoints it as completed with the cursor cleared.
        manager.save_state.assert_called_once_with(
            DeepsourceResumeConfig(completed_repositories=["alpha", "gamma"], current_repository=None, cursor=None)
        )

    def test_fan_out_checkpoints_mid_repository(self) -> None:
        session = MagicMock()
        responses = [
            _repo_names_response([("alpha", True)]),
            _connection_response(
                "repository", "issues", [{"id": "i-1"}], True, "inner-c1", parent_extra={"id": "RID", "name": "alpha"}
            ),
            _connection_response(
                "repository", "issues", [{"id": "i-2"}], False, None, parent_extra={"id": "RID", "name": "alpha"}
            ),
        ]
        _capture_post_calls(session, responses)

        manager = _make_manager()
        list(_fan_out_connection_rows(session, "acme", "GITHUB", "issues", MagicMock(), manager))

        assert manager.save_state.call_args_list == [
            ((DeepsourceResumeConfig(completed_repositories=[], current_repository="alpha", cursor="inner-c1"),),),
            ((DeepsourceResumeConfig(completed_repositories=["alpha"], current_repository=None, cursor=None),),),
        ]

    def test_fan_out_skips_repository_deleted_mid_sync(self) -> None:
        session = MagicMock()
        responses = [
            _repo_names_response([("gone", True), ("alive", True)]),
            _null_parent_response("repository"),
            _connection_response(
                "repository",
                "issueOccurrences",
                [{"id": "occ-1"}],
                False,
                None,
                parent_extra={"id": "RID", "name": "alive"},
            ),
        ]
        _capture_post_calls(session, responses)

        manager = _make_manager()
        pages = list(_fan_out_connection_rows(session, "acme", "GITHUB", "issue_occurrences", MagicMock(), manager))

        assert [row["id"] for page in pages for row in page] == ["occ-1"]
        assert manager.save_state.call_args_list[-1] == (
            (DeepsourceResumeConfig(completed_repositories=["alive", "gone"], current_repository=None, cursor=None),),
        )


class TestPerRepositoryObjects:
    def test_metrics_rows_flattened_per_item(self) -> None:
        metrics_response = MagicMock()
        metrics_response.status_code = 200
        metrics_response.ok = True
        metrics_response.json.return_value = {
            "data": {
                "repository": {
                    "id": "RID",
                    "name": "alpha",
                    "metrics": [
                        {
                            "name": "Line Coverage",
                            "shortcode": "LCV",
                            "description": "desc",
                            "positiveDirection": "UPWARD",
                            "unit": "%",
                            "isReported": True,
                            "isThresholdEnforced": False,
                            "items": [
                                {
                                    "id": "item-1",
                                    "key": "AGGREGATE",
                                    "threshold": 80,
                                    "latestValue": 91.5,
                                    "latestValueDisplay": "91.5%",
                                    "thresholdStatus": "PASSING",
                                },
                                {
                                    "id": "item-2",
                                    "key": "PYTHON",
                                    "threshold": None,
                                    "latestValue": 88.0,
                                    "latestValueDisplay": "88%",
                                    "thresholdStatus": None,
                                },
                            ],
                        }
                    ],
                }
            }
        }
        session = MagicMock()
        _capture_post_calls(session, [_repo_names_response([("alpha", True)]), metrics_response])

        manager = _make_manager()
        pages = list(_per_repository_object_rows(session, "acme", "GITHUB", "metrics", MagicMock(), manager))

        rows = [row for page in pages for row in page]
        assert [row["id"] for row in rows] == ["item-1", "item-2"]
        assert all(row["metricShortcode"] == "LCV" for row in rows)
        assert all(row["repositoryId"] == "RID" and row["repositoryName"] == "alpha" for row in rows)
        manager.save_state.assert_called_once_with(
            DeepsourceResumeConfig(completed_repositories=["alpha"], current_repository=None, cursor=None)
        )

    def test_report_rows_one_per_report_key(self) -> None:
        repository = {
            "id": "RID",
            "name": "alpha",
            "reports": {
                "owaspTop10": {"key": "OWASP_TOP_10", "title": "OWASP Top 10", "currentValue": 3, "status": "FAILING"},
                "codeHealthTrend": {"key": "CODE_HEALTH_TREND", "title": "Code health trend", "currentValue": 12},
            },
        }

        rows = _report_rows(repository)

        assert rows == [
            {
                "key": "OWASP_TOP_10",
                "title": "OWASP Top 10",
                "currentValue": 3,
                "status": "FAILING",
                "repositoryId": "RID",
                "repositoryName": "alpha",
            },
            {
                "key": "CODE_HEALTH_TREND",
                "title": "Code health trend",
                "currentValue": 12,
                "status": None,
                "repositoryId": "RID",
                "repositoryName": "alpha",
            },
        ]

    def test_metric_rows_empty_when_repository_has_no_metrics(self) -> None:
        assert _metric_rows({"id": "RID", "name": "alpha", "metrics": None}) == []


class TestRetriesAndErrors:
    @patch("time.sleep", return_value=None)
    def test_429_is_retried_then_succeeds(self, _mock_sleep: MagicMock) -> None:
        rate_limited = _error_response(429, "Too Many Requests")
        rate_limited.headers = {"Retry-After": "0"}
        session = MagicMock()
        session.post.side_effect = [
            rate_limited,
            _connection_response("account", "repositories", [{"id": "a"}], False, None),
        ]

        pages = list(_repositories_rows(session, "acme", "GITHUB", MagicMock(), _make_manager()))

        assert pages == [[{"id": "a"}]]
        assert session.post.call_count == 2

    @patch("time.sleep", return_value=None)
    def test_persistent_429_raises_retryable_error(self, _mock_sleep: MagicMock) -> None:
        rate_limited = _error_response(429, "Too Many Requests")
        rate_limited.headers = {"Retry-After": "0"}
        session = MagicMock()
        session.post.side_effect = [rate_limited for _ in range(DEEPSOURCE_MAX_RETRY_ATTEMPTS)]

        with pytest.raises(DeepsourceRetryableError):
            list(_repositories_rows(session, "acme", "GITHUB", MagicMock(), _make_manager()))

        assert session.post.call_count == DEEPSOURCE_MAX_RETRY_ATTEMPTS

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized", {"message": "Authentication required"}),
            ("forbidden", 403, "Forbidden", None),
        ]
    )
    def test_auth_errors_raise_messages_matched_by_non_retryable_errors(
        self,
        _name: str,
        status_code: int,
        reason: str,
        body: dict[str, Any] | None,
    ) -> None:
        session = MagicMock()
        session.post.side_effect = [_error_response(status_code, reason, body)]

        with pytest.raises(Exception) as exc_info:
            list(_repositories_rows(session, "acme", "GITHUB", MagicMock(), _make_manager()))

        # The raised message must stay matchable by the source's non-retryable error keys,
        # otherwise bad credentials retry forever.
        non_retryable = DeepsourceSource().get_non_retryable_errors()
        assert any(key in str(exc_info.value) for key in non_retryable)

    def test_graphql_errors_raise(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {"errors": [{"message": "Something went wrong"}]}
        session = MagicMock()
        session.post.side_effect = [response]

        with pytest.raises(Exception, match="DeepSource GraphQL error: Something went wrong"):
            list(_repositories_rows(session, "acme", "GITHUB", MagicMock(), _make_manager()))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, {"data": {"viewer": {"email": "a@b.c"}, "account": {"id": "AID"}}}, True, None),
            (
                "token_ok_account_missing",
                200,
                {"data": {"viewer": {"email": "a@b.c"}, "account": None}},
                False,
                "DeepSource account not found",
            ),
            (
                "bad_token",
                401,
                {"message": "Authentication required"},
                False,
                "Invalid DeepSource personal access token",
            ),
            (
                "graphql_error_no_viewer",
                200,
                {"data": {"viewer": None, "account": None}, "errors": [{"message": "boom"}]},
                False,
                "DeepSource API error",
            ),
        ]
    )
    @patch(_SESSION_PATCH)
    def test_validation_outcomes(
        self,
        _name: str,
        status_code: int,
        body: dict[str, Any],
        expected_valid: bool,
        expected_error_fragment: str | None,
        mock_session_cls: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body
        session = MagicMock()
        session.post.return_value = response
        mock_session_cls.return_value = session

        valid, error = validate_credentials("token", "acme", "GITHUB")

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_error_fragment in error
