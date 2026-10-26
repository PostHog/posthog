from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.deepsource import (
    DEEPSOURCE_MAX_RETRY_ATTEMPTS,
    DeepsourceResumeConfig,
    DeepsourceRetryableError,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deepsource.source import DeepsourceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deepsource import (
    DeepsourceSourceConfig,
)

_CONFIG = DeepsourceSourceConfig(api_token="token", account_login="acme", vcs_provider="GITHUB")


def _driver() -> SourceDriver:
    return SourceDriver(DeepsourceSource(), _CONFIG)


def _variables(request: RecordedRequest) -> dict[str, Any]:
    return request.json()["variables"]


def _connection_response(
    parent_field: str,
    connection_field: str,
    nodes: list[dict[str, Any]],
    has_next_page: bool,
    end_cursor: str | None,
    parent_extra: dict[str, Any] | None = None,
) -> ScriptedResponse:
    return ScriptedResponse(
        json={
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
    )


def _root_connection_response(
    connection_field: str,
    nodes: list[dict[str, Any]],
    has_next_page: bool,
    end_cursor: str | None,
) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {
                connection_field: {
                    "edges": [{"node": node} for node in nodes],
                    "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
                }
            }
        }
    )


def _null_parent_response(parent_field: str) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {parent_field: None}})


def _repo_names_response(repos: list[tuple[str, bool]]) -> ScriptedResponse:
    return _connection_response(
        "account",
        "repositories",
        [{"name": name, "isActivated": activated} for name, activated in repos],
        False,
        None,
    )


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
        responses = [
            _connection_response("account", "repositories", [{"id": f"repo-{i}", "name": f"repo-{i}"}], has_next, end)
            for i, (has_next, end) in enumerate(page_specs)
        ]
        saved = DeepsourceResumeConfig(cursor=saved_cursor) if saved_cursor else None

        result = _driver().run("repositories", responses, resume_state=saved)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [f"repo-{i}" for i in range(len(page_specs))]
        assert _variables(result.requests[0])["cursor"] == first_request_cursor
        assert result.saved_states == [DeepsourceResumeConfig(cursor=c) for c in expected_checkpoints]
        expected_committed = ([saved] if saved is not None else []) + [
            DeepsourceResumeConfig(cursor=c) for c in expected_checkpoints
        ]
        assert result.committed_states == expected_committed

    def test_raises_when_has_next_page_but_cursor_missing(self) -> None:
        result = _driver().run(
            "repositories", [_connection_response("account", "repositories", [{"id": "a"}], True, None)]
        )

        assert isinstance(result.raised, Exception)
        assert "endCursor is empty" in str(result.raised)

    def test_stalled_cursor_raises_instead_of_refetching_the_same_page(self) -> None:
        result = _driver().run(
            "repositories",
            [
                _connection_response("account", "repositories", [{"id": "a"}], True, "c1"),
                _connection_response("account", "repositories", [{"id": "a"}], True, "c1"),
            ],
        )

        assert isinstance(result.raised, Exception)
        assert "endCursor did not advance past 'c1'" in str(result.raised)
        assert len(result.requests) == 2

    def test_missing_account_raises_actionable_error(self) -> None:
        result = _driver().run("repositories", [_null_parent_response("account")])

        assert isinstance(result.raised, Exception)
        assert "DeepSource account not found" in str(result.raised)


class TestFanOut:
    def test_fan_out_skips_completed_and_unactivated_and_resumes_cursor(self) -> None:
        result = _driver().run(
            "analysis_runs",
            [
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
            ],
            resume_state=DeepsourceResumeConfig(
                completed_repositories=["alpha"], current_repository="gamma", cursor="saved-inner"
            ),
        )

        # Only gamma is walked, resuming from the saved inner cursor.
        assert result.raised is None
        assert len(result.requests) == 2
        assert _variables(result.requests[1])["name"] == "gamma"
        assert _variables(result.requests[1])["cursor"] == "saved-inner"
        # Rows carry the repository context needed downstream.
        assert result.items == [
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
        assert result.saved_states == [
            DeepsourceResumeConfig(completed_repositories=["alpha", "gamma"], current_repository=None, cursor=None)
        ]

    def test_fan_out_checkpoints_mid_repository(self) -> None:
        result = _driver().run(
            "issues",
            [
                _repo_names_response([("alpha", True)]),
                _connection_response(
                    "repository",
                    "issues",
                    [{"id": "i-1"}],
                    True,
                    "inner-c1",
                    parent_extra={"id": "RID", "name": "alpha"},
                ),
                _connection_response(
                    "repository",
                    "issues",
                    [{"id": "i-2"}],
                    False,
                    None,
                    parent_extra={"id": "RID", "name": "alpha"},
                ),
            ],
        )

        assert result.raised is None
        assert result.saved_states == [
            DeepsourceResumeConfig(completed_repositories=[], current_repository="alpha", cursor="inner-c1"),
            DeepsourceResumeConfig(completed_repositories=["alpha"], current_repository=None, cursor=None),
        ]
        assert result.committed_states == [
            DeepsourceResumeConfig(completed_repositories=[], current_repository="alpha", cursor="inner-c1")
        ]

    def test_fan_out_skips_repository_deleted_mid_sync(self) -> None:
        result = _driver().run(
            "issue_occurrences",
            [
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
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["occ-1"]
        assert result.saved_states[-1] == DeepsourceResumeConfig(
            completed_repositories=["alive", "gone"], current_repository=None, cursor=None
        )


class TestChecksFanOut:
    """Checks ride nested inside the analysis-run walk, so one run page can expand into many rows."""

    @staticmethod
    def _run_node(run_id: str, checks: list[dict[str, Any]], has_next_page: bool, end_cursor: str | None) -> dict:
        return {
            "id": run_id,
            "runUid": f"uid-{run_id}",
            "commitOid": "abc123",
            "branchName": "main",
            "checks": {
                "edges": [{"node": check} for check in checks],
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
            },
        }

    def test_each_run_expands_into_one_row_per_check(self) -> None:
        result = _driver().run(
            "checks",
            [
                _repo_names_response([("alpha", True)]),
                _connection_response(
                    "repository",
                    "analysisRuns",
                    [
                        self._run_node("run-1", [{"id": "chk-1"}, {"id": "chk-2"}], False, None),
                        self._run_node("run-2", [{"id": "chk-3"}], False, None),
                    ],
                    False,
                    None,
                    parent_extra={"id": "RID", "name": "alpha"},
                ),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["chk-1", "chk-2", "chk-3"]
        assert [row["analysisRunId"] for row in result.rows] == ["run-1", "run-1", "run-2"]
        assert all(row["repositoryId"] == "RID" and row["repositoryName"] == "alpha" for row in result.rows)
        assert all(row["analysisRunUid"] == f"uid-{row['analysisRunId']}" for row in result.rows)

    def test_run_with_more_checks_than_one_page_is_followed_up(self) -> None:
        result = _driver().run(
            "checks",
            [
                _repo_names_response([("alpha", True)]),
                _connection_response(
                    "repository",
                    "analysisRuns",
                    [self._run_node("run-1", [{"id": "chk-1"}], True, "check-c1")],
                    False,
                    None,
                    parent_extra={"id": "RID", "name": "alpha"},
                ),
                _connection_response("node", "checks", [{"id": "chk-2"}], False, None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["chk-1", "chk-2"]
        # The follow-up resumes the run's own check connection, not the analysis-run walk.
        assert _variables(result.requests[2]) == {"id": "run-1", "checkPageSize": 50, "cursor": "check-c1"}
        # The trailing check still carries the run and repository context.
        assert result.rows[1]["analysisRunId"] == "run-1" and result.rows[1]["repositoryName"] == "alpha"

    def test_run_lost_during_check_follow_up_raises(self) -> None:
        result = _driver().run(
            "checks",
            [
                _repo_names_response([("alpha", True)]),
                _connection_response(
                    "repository",
                    "analysisRuns",
                    [self._run_node("run-1", [{"id": "chk-1"}], True, "check-c1")],
                    False,
                    None,
                    parent_extra={"id": "RID", "name": "alpha"},
                ),
                _null_parent_response("node"),
            ],
        )

        # Skipping instead would checkpoint run-1 as complete with only its first check page.
        assert isinstance(result.raised, Exception)
        assert "analysis run run-1 disappeared" in str(result.raised)

    def test_truncated_check_page_raises_rather_than_dropping_checks(self) -> None:
        result = _driver().run(
            "checks",
            [
                _repo_names_response([("alpha", True)]),
                _connection_response(
                    "repository",
                    "analysisRuns",
                    [self._run_node("run-1", [{"id": "chk-1"}], True, None)],
                    False,
                    None,
                    parent_extra={"id": "RID", "name": "alpha"},
                ),
            ],
        )

        assert isinstance(result.raised, Exception)
        assert "endCursor is empty for checks" in str(result.raised)


class TestRootConnection:
    def test_analyzers_paginate_and_checkpoint_without_an_account(self) -> None:
        result = _driver().run(
            "analyzers",
            [
                _root_connection_response("analyzers", [{"id": "an-1", "shortcode": "python"}], True, "c1"),
                _root_connection_response("analyzers", [{"id": "an-2", "shortcode": "go"}], False, None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["an-1", "an-2"]
        # The analyzer catalog is account-independent, so the query carries no account filter.
        assert all("login" not in _variables(request) for request in result.requests)
        assert result.saved_states == [DeepsourceResumeConfig(cursor="c1")]


class TestPerRepositoryObjects:
    def test_metrics_rows_flattened_per_item(self) -> None:
        metrics_response = ScriptedResponse(
            json={
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
        )
        result = _driver().run("metrics", [_repo_names_response([("alpha", True)]), metrics_response])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["item-1", "item-2"]
        assert all(row["metricShortcode"] == "LCV" for row in result.rows)
        assert all(row["repositoryId"] == "RID" and row["repositoryName"] == "alpha" for row in result.rows)
        assert result.saved_states == [
            DeepsourceResumeConfig(completed_repositories=["alpha"], current_repository=None, cursor=None)
        ]

    def test_report_rows_one_per_report_key(self) -> None:
        result = _driver().run(
            "reports",
            [
                _repo_names_response([("alpha", True)]),
                ScriptedResponse(
                    json={
                        "data": {
                            "repository": {
                                "id": "RID",
                                "name": "alpha",
                                "reports": {
                                    "owaspTop10": {
                                        "key": "OWASP_TOP_10",
                                        "title": "OWASP Top 10",
                                        "currentValue": 3,
                                        "status": "FAILING",
                                    },
                                    "codeHealthTrend": {
                                        "key": "CODE_HEALTH_TREND",
                                        "title": "Code health trend",
                                        "currentValue": 12,
                                    },
                                },
                            }
                        }
                    }
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [
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


class TestRetriesAndErrors:
    def test_429_is_retried_then_succeeds(self) -> None:
        result = _driver().run(
            "repositories",
            [
                ScriptedResponse(status=429, headers={"Retry-After": "0"}),
                _connection_response("account", "repositories", [{"id": "a"}], False, None),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "a"}]]
        assert len(result.requests) == 2

    def test_persistent_429_raises_retryable_error(self) -> None:
        result = _driver().run("repositories", always(ScriptedResponse(status=429, headers={"Retry-After": "0"})))

        assert isinstance(result.raised, DeepsourceRetryableError)
        assert len(result.requests) == DEEPSOURCE_MAX_RETRY_ATTEMPTS

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
        result = _driver().run("repositories", [ScriptedResponse(status=status_code, json=body)])

        assert isinstance(result.raised, Exception)
        assert reason in str(result.raised)
        # The raised message must stay matchable by the source's non-retryable error keys,
        # otherwise bad credentials retry forever.
        non_retryable = DeepsourceSource().get_non_retryable_errors()
        assert any(key in str(result.raised) for key in non_retryable)

    def test_graphql_errors_raise(self) -> None:
        result = _driver().run(
            "repositories", [ScriptedResponse(json={"errors": [{"message": "Something went wrong"}]})]
        )

        assert isinstance(result.raised, Exception)
        assert "DeepSource GraphQL error: Something went wrong" in str(result.raised)


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
                "graphql_error_no_viewer",
                200,
                {"data": {"viewer": None, "account": None}, "errors": [{"message": "boom"}]},
                False,
                "DeepSource API error",
            ),
        ]
    )
    def test_validation_outcomes(
        self,
        _name: str,
        status_code: int,
        body: dict[str, Any],
        expected_valid: bool,
        expected_error_fragment: str | None,
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json=body)]) as network:
            valid, error = validate_credentials("token", "acme", "GITHUB")

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_error_fragment in error
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == "Bearer token"
        assert _variables(network.requests_log[0]) == {"login": "acme", "vcsProvider": "GITHUB"}
