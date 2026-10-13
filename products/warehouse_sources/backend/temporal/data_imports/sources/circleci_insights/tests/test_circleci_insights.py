from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.circleci_insights import (
    CircleciInsightsResumeConfig,
    CircleciInsightsRetryableError,
    _format_start_date,
    _format_start_date_param,
    get_rows,
    parse_project_slugs,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.settings import (
    CIRCLECI_INSIGHTS_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.source import (
    CircleciInsightsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.circleciinsights import (
    CircleciInsightsSourceConfig,
)

PATCH_SESSION = "products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.circleci_insights.make_tracked_session"


def _driver(
    project_slugs: str = "gh/a/one",
    reporting_window: Literal["last-24-hours", "last-7-days", "last-30-days", "last-60-days", "last-90-days"] = (
        "last-90-days"
    ),
    branch_scope: Literal["default_branch", "all_branches"] = "default_branch",
) -> SourceDriver:
    return SourceDriver(
        CircleciInsightsSource(),
        CircleciInsightsSourceConfig(
            api_token="token",
            project_slugs=project_slugs,
            reporting_window=reporting_window,
            branch_scope=branch_scope,
        ),
    )


def _page(items: list[dict[str, Any]], next_token: str | None) -> dict[str, Any]:
    return {"items": items, "next_page_token": next_token}


def _scripted_page(items: list[dict[str, Any]], next_token: str | None) -> ScriptedResponse:
    return ScriptedResponse(json=_page(items, next_token))


def _make_manager(resume_state: CircleciInsightsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    response.json.return_value = body
    return response


def _rows(batches: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row for batch in batches for row in batch]


class TestSlugParsing:
    @parameterized.expand(
        [
            ("gh/posthog/posthog", ["gh/posthog/posthog"]),
            ("gh/a/b, gh/a/c", ["gh/a/b", "gh/a/c"]),
            ("gh/a/b\ngh/a/c", ["gh/a/b", "gh/a/c"]),
            (" gh/a/b ,, gh/a/b ", ["gh/a/b"]),
            ("/gh/a/b/", ["gh/a/b"]),
            ("", []),
            ("  ,\n ", []),
        ]
    )
    def test_parse_project_slugs(self, raw, expected):
        assert parse_project_slugs(raw) == expected


class TestFormatStartDate:
    @parameterized.expand(
        [
            (datetime(2026, 7, 1, 13, 30, tzinfo=UTC), "2026-07-01"),
            (date(2026, 7, 1), "2026-07-01"),
            ("2026-07-01T13:30:00Z", "2026-07-01"),
            (None, None),
            ("", None),
        ]
    )
    def test_formats_as_date_only(self, value, expected):
        assert _format_start_date(value) == expected

    @parameterized.expand(
        [
            (datetime(2026, 7, 1, 13, 30, tzinfo=UTC), False, "2026-07-01"),
            (datetime(2026, 7, 1, 13, 30, tzinfo=UTC), True, "2026-07-01T00:00:00Z"),
            (None, True, None),
        ]
    )
    def test_timestamp_form_keeps_the_same_watermark_day(self, value, needs_timestamp, expected):
        assert _format_start_date_param(value, needs_timestamp) == expected


class TestValidateCredentials:
    def test_bad_slug_format_short_circuits_without_network(self):
        with scripted_network([]) as network:
            is_valid, error = validate_credentials("token", "not-a-slug")

        assert is_valid is False
        assert error is not None and "not-a-slug" in error
        assert network.requests_log == []

    def test_empty_slugs_rejected(self):
        with scripted_network([]) as network:
            is_valid, error = validate_credentials("token", "  ")

        assert is_valid is False
        assert error is not None
        assert network.requests_log == []

    @parameterized.expand(
        [
            (401, None, False),
            (200, 404, False),
            (200, 403, False),
            (200, 200, True),
        ]
    )
    def test_status_mapping(self, me_status, project_status, expected):
        responses = [ScriptedResponse(status=me_status, json={})]
        if project_status is not None:
            responses.append(ScriptedResponse(status=project_status, json={"items": [], "next_page_token": None}))

        with scripted_network(responses) as network:
            is_valid, error = validate_credentials("token", "gh/posthog/posthog")

        assert is_valid is expected
        assert (error is None) is expected
        expected_paths = ["/api/v2/me"]
        if project_status is not None:
            expected_paths.append("/api/v2/insights/gh/posthog/posthog/workflows")
        assert [request.path for request in network.requests_log] == expected_paths

    def test_swallows_connection_errors(self):
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, error = validate_credentials("token", "gh/posthog/posthog")

        assert is_valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/api/v2/me"}


class TestWorkflowMetricsRows:
    def test_paginates_and_injects_project_slug_across_projects(self):
        result = _driver("gh/a/one, gh/a/two").run(
            "workflow_metrics",
            route(
                {
                    "/api/v2/insights/gh/a/one/workflows": [
                        _scripted_page([{"name": "ci"}], "token-2"),
                        _scripted_page([{"name": "release"}], None),
                    ],
                    "/api/v2/insights/gh/a/two/workflows": [_scripted_page([{"name": "deploy"}], None)],
                }
            ),
        )

        assert result.raised is None
        assert [(row["project_slug"], row["name"]) for row in result.rows] == [
            ("gh/a/one", "ci"),
            ("gh/a/one", "release"),
            ("gh/a/two", "deploy"),
        ]
        assert result.paths == [
            "/api/v2/insights/gh/a/one/workflows",
            "/api/v2/insights/gh/a/one/workflows",
            "/api/v2/insights/gh/a/two/workflows",
        ]
        assert result.requests[0].param("reporting-window") == "last-90-days"
        assert result.requests[1].param("page-token") == "token-2"

    def test_state_saved_after_each_page_and_on_project_completion(self):
        result = _driver().run(
            "workflow_metrics",
            [_scripted_page([{"name": "ci"}], "token-2"), _scripted_page([{"name": "release"}], None)],
        )

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["ci", "release"]
        assert result.saved_states == [
            CircleciInsightsResumeConfig(slug="gh/a/one", next_page_token="token-2"),
            CircleciInsightsResumeConfig(slug="gh/a/one", slug_done=True),
        ]
        assert result.committed_states == [CircleciInsightsResumeConfig(slug="gh/a/one", next_page_token="token-2")]
        assert result.final_state == CircleciInsightsResumeConfig(slug="gh/a/one", next_page_token="token-2")

    def test_resume_skips_completed_project(self):
        result = _driver("gh/a/one, gh/a/two").run(
            "workflow_metrics",
            [_scripted_page([{"name": "deploy"}], None)],
            resume_state=CircleciInsightsResumeConfig(slug="gh/a/one", slug_done=True),
        )

        assert result.raised is None
        assert [row["project_slug"] for row in result.rows] == ["gh/a/two"]
        assert result.paths == ["/api/v2/insights/gh/a/two/workflows"]

    def test_resume_with_unknown_slug_starts_over(self):
        result = _driver().run(
            "workflow_metrics",
            [_scripted_page([{"name": "ci"}], None)],
            resume_state=CircleciInsightsResumeConfig(slug="gh/gone/away", next_page_token="stale"),
        )

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["ci"]
        assert result.requests[0].param("page-token") is None

    def test_unknown_endpoint_raises(self):
        manager = CircleciInsightsSource().get_resumable_source_manager(source_inputs("nope"))
        with pytest.raises(ValueError, match="Unknown CircleCI Insights endpoint"):
            list(get_rows("token", "gh/a/one", "nope", mock.MagicMock(), manager))


class TestWorkflowRunsFanOut:
    def test_resume_mid_workflow_skips_earlier_workflows(self):
        result = _driver().run(
            "workflow_runs",
            route(
                {
                    "/api/v2/insights/gh/a/one/workflows": [
                        _scripted_page([{"name": "ci"}, {"name": "release"}, {"name": "deploy"}], None)
                    ],
                    "/api/v2/insights/gh/a/one/workflows/release": [_scripted_page([{"id": "r2"}], None)],
                    "/api/v2/insights/gh/a/one/workflows/deploy": [_scripted_page([{"id": "r3"}], None)],
                }
            ),
            resume_state=CircleciInsightsResumeConfig(
                slug="gh/a/one", workflow_name="release", next_page_token="wf-token"
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["r2", "r3"]
        assert result.paths == [
            "/api/v2/insights/gh/a/one/workflows",
            "/api/v2/insights/gh/a/one/workflows/release",
            "/api/v2/insights/gh/a/one/workflows/deploy",
        ]
        assert result.requests[1].param("page-token") == "wf-token"
        # Workflows after the resume point start from their first page.
        assert result.requests[2].param("page-token") is None

    def test_state_saved_with_workflow_position(self):
        result = _driver().run(
            "workflow_runs",
            route(
                {
                    "/api/v2/insights/gh/a/one/workflows": [_scripted_page([{"name": "ci"}], None)],
                    "/api/v2/insights/gh/a/one/workflows/ci": [
                        _scripted_page([{"id": "r1"}], "run-token-2"),
                        _scripted_page([{"id": "r2"}], None),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.saved_states[0] == CircleciInsightsResumeConfig(
            slug="gh/a/one", workflow_name="ci", next_page_token="run-token-2"
        )


class TestJobMetricsFanOut:
    def test_job_rows_carry_parents_and_reporting_window(self):
        result = _driver(reporting_window="last-30-days").run(
            "job_metrics",
            route(
                {
                    "/api/v2/insights/gh/a/one/workflows": [_scripted_page([{"name": "ci"}], None)],
                    "/api/v2/insights/gh/a/one/workflows/ci/jobs": [
                        _scripted_page([{"name": "build"}, {"name": "test"}], None)
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [(row["project_slug"], row["workflow_name"], row["name"]) for row in result.rows] == [
            ("gh/a/one", "ci", "build"),
            ("gh/a/one", "ci", "test"),
        ]
        assert result.requests[1].param("reporting-window") == "last-30-days"


class TestJobTimeseriesFanOut:
    def test_all_branches_widens_discovery_but_not_the_timeseries_request(self):
        logger = mock.MagicMock()
        result = _driver(branch_scope="all_branches").run(
            "job_timeseries",
            route(
                {
                    "/api/v2/insights/gh/a/one/workflows": [_scripted_page([{"name": "ci"}], None)],
                    "/api/v2/insights/time-series/gh/a/one/workflows/ci/jobs": [_scripted_page([], None)],
                }
            ),
            logger=logger,
        )

        assert result.raised is None
        assert result.requests[0].param("all-branches") == "true"
        assert result.requests[1].param("all-branches") is None
        # The setting silently cannot reach these rows, so the sync log has to say so.
        assert "default branch only" in logger.warning.call_args.args[0]

    @parameterized.expand([(True, ["2026-07-01T00:00:00Z"]), (False, None)])
    def test_start_date_sent_only_on_incremental(self, incremental, expected):
        result = _driver().run(
            "job_timeseries",
            route(
                {
                    "/api/v2/insights/gh/a/one/workflows": [_scripted_page([{"name": "ci"}], None)],
                    "/api/v2/insights/time-series/gh/a/one/workflows/ci/jobs": [_scripted_page([], None)],
                }
            ),
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        )

        assert result.raised is None
        start_date = result.requests[1].query.get("start-date")
        assert (list(start_date) if start_date is not None else None) == expected


class TestWorkflowSummaryFanOut:
    def test_state_saved_per_workflow_and_resume_skips_earlier_ones(self):
        result = _driver().run(
            "workflow_summary",
            route(
                {
                    "/api/v2/insights/gh/a/one/workflows": [
                        _scripted_page([{"name": "ci"}, {"name": "release"}, {"name": "deploy"}], None)
                    ],
                    "/api/v2/insights/gh/a/one/workflows/release/summary": [
                        ScriptedResponse(json={"metrics": {}, "trends": {}})
                    ],
                    "/api/v2/insights/gh/a/one/workflows/deploy/summary": [
                        ScriptedResponse(json={"metrics": {}, "trends": {}})
                    ],
                }
            ),
            resume_state=CircleciInsightsResumeConfig(slug="gh/a/one", workflow_name="release"),
        )

        assert result.raised is None
        assert [row["workflow_name"] for row in result.rows] == ["release", "deploy"]
        assert "/api/v2/insights/gh/a/one/workflows/ci/summary" not in result.paths
        assert [state.workflow_name for state in result.saved_states[:2]] == ["release", "deploy"]


class TestWorkflowTestMetricsFanOut:
    def test_merges_the_two_test_lists_on_test_identity(self):
        shared = {"job_name": "test", "classname": "suite.A", "test_name": "t1", "failed_runs": 4, "p95_duration": 9.0}
        result = _driver().run(
            "workflow_test_metrics",
            route(
                {
                    "/api/v2/insights/gh/a/one/workflows": [_scripted_page([{"name": "ci"}], None)],
                    "/api/v2/insights/gh/a/one/workflows/ci/test-metrics": [
                        ScriptedResponse(
                            json={
                                "average_test_count": 12,
                                "most_failed_tests": [shared],
                                "slowest_tests": [
                                    shared,
                                    {
                                        "job_name": "test",
                                        "classname": "suite.B",
                                        "test_name": "t2",
                                        "p95_duration": 30.0,
                                    },
                                ],
                            }
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        # The same test appears in both lists; the delta merge only dedupes across syncs, so a
        # duplicate here would seed duplicate rows under the composite primary key.
        assert [(row["classname"], row["test_name"]) for row in result.rows] == [("suite.A", "t1"), ("suite.B", "t2")]
        assert all(row["project_slug"] == "gh/a/one" and row["workflow_name"] == "ci" for row in result.rows)


class TestBranchesRows:
    def test_branch_names_become_rows_with_project_identifiers(self):
        result = _driver().run(
            "branches",
            [
                ScriptedResponse(
                    json={"org_id": "org-1", "project_id": "proj-1", "branches": ["master", "feature/x", "", None]}
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"project_slug": "gh/a/one", "branch": "master", "org_id": "org-1", "project_id": "proj-1"},
            {"project_slug": "gh/a/one", "branch": "feature/x", "org_id": "org-1", "project_id": "proj-1"},
        ]

    def test_unexpected_shape_syncs_zero_rows(self):
        logger = mock.MagicMock()
        result = _driver().run("branches", [ScriptedResponse(json={"message": "no insights"})], logger=logger)

        assert result.raised is None
        assert result.rows == []
        logger.warning.assert_called_once()


class TestFlakyTestsRows:
    def test_unwraps_envelope_and_injects_project_slug(self):
        result = _driver().run(
            "flaky_tests",
            [
                ScriptedResponse(
                    json={
                        "flaky_tests": [{"test_name": "t1", "classname": "c", "job_name": "j", "workflow_name": "w"}],
                        "total_flaky_tests": 1,
                    }
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {
                "test_name": "t1",
                "classname": "c",
                "job_name": "j",
                "workflow_name": "w",
                "project_slug": "gh/a/one",
            }
        ]


class TestOrgSummaryRows:
    def test_projects_collapse_to_one_org_fetch(self):
        result = _driver("gh/a/one, gh/a/two").run(
            "org_summary_metrics",
            [
                ScriptedResponse(
                    json={
                        "org_data": {"metrics": {}},
                        "org_project_data": [{"project_name": "one"}, {"project_name": "two"}],
                    }
                )
            ],
        )

        assert result.raised is None
        assert [(row["org_slug"], row["project_name"]) for row in result.rows] == [("gh/a", "one"), ("gh/a", "two")]
        assert result.paths == ["/api/v2/insights/gh/a/summary"]

    def test_unexpected_shape_syncs_zero_rows(self):
        logger = mock.MagicMock()
        result = _driver().run(
            "org_summary_metrics", [ScriptedResponse(json={"message": "no insights"})], logger=logger
        )

        assert result.raised is None
        assert result.rows == []
        logger.warning.assert_called_once()


class TestRetryBehavior:
    # Patch the sleep tenacity actually uses; the wait time is computed by `_retry_wait`, so a
    # single sleep of exactly `retry_after` proves we honor the header without double-waiting.
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(PATCH_SESSION)
    def test_429_honors_rate_limit_headers_then_retries(self, mock_session, mock_sleep):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=429, headers={"retry-after": "7"}),
            _response(_page([{"name": "ci"}], None)),
        ]

        batches = list(get_rows("token", "gh/a/one", "workflow_metrics", mock.MagicMock(), _make_manager()))

        assert [row["name"] for row in _rows(batches)] == ["ci"]
        mock_sleep.assert_called_once_with(7)

    def test_5xx_retries_then_succeeds(self):
        result = _driver().run(
            "workflow_metrics",
            [ScriptedResponse(status=503), _scripted_page([{"name": "ci"}], None)],
        )

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["ci"]
        assert result.paths == ["/api/v2/insights/gh/a/one/workflows"] * 2

    def test_persistent_5xx_raises_after_max_retries(self):
        result = _driver().run("workflow_metrics", always(ScriptedResponse(status=500)))

        assert isinstance(result.raised, CircleciInsightsRetryableError)
        assert len(result.requests) > 5
        assert set(result.paths) == {"/api/v2/insights/gh/a/one/workflows"}

    def test_4xx_raises_immediately(self):
        result = _driver().run("workflow_metrics", [ScriptedResponse(status=401, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error" in str(result.raised)
        assert len(result.requests) == 1


class TestPageCap:
    def test_page_cap_stops_pagination_and_logs(self):
        logger = mock.MagicMock()
        result = _driver().run(
            "workflow_metrics",
            always(_scripted_page([{"name": "ci"}], "always-more")),
            logger=logger,
        )

        assert result.raised is None
        assert len(result.items) == 100
        assert len(result.requests) == 100
        logger.warning.assert_called_once()
        assert "page cap" in logger.warning.call_args.args[0]


class TestCircleciInsightsSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CIRCLECI_INSIGHTS_ENDPOINTS[endpoint]
        result = _driver(project_slugs="").run(endpoint, [])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @parameterized.expand([("workflow_runs",), ("job_timeseries",)])
    def test_row_level_endpoints_declare_desc_sort(self, endpoint):
        # These are the incremental endpoints. Desc defers the watermark commit to the end of
        # the sync; asc would checkpoint per batch, which fan-out over workflows makes unsafe.
        result = _driver(project_slugs="").run(endpoint, [])

        assert result.raised is None
        assert result.response is not None
        assert result.response.sort_mode == "desc"
