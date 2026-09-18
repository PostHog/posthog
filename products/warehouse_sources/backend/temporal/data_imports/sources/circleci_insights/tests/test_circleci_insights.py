from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.circleci_insights import (
    CircleciInsightsResumeConfig,
    CircleciInsightsRetryableError,
    _format_start_date,
    _format_start_date_param,
    circleci_insights_source,
    get_rows,
    org_slugs_from_projects,
    parse_project_slugs,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.settings import (
    CIRCLECI_INSIGHTS_ENDPOINTS,
    ENDPOINTS,
)

PATCH_SESSION = "products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.circleci_insights.make_tracked_session"


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


def _page(items: list[dict[str, Any]], next_token: str | None) -> dict[str, Any]:
    return {"items": items, "next_page_token": next_token}


def _route_session(mock_session: mock.MagicMock, routes: dict[str, list[dict[str, Any]] | dict[str, Any]]) -> None:
    """Route GET calls by path; values are either a body dict or a list of bodies consumed in order."""
    state: dict[str, int] = {}

    def get(url: str, **kwargs: Any) -> mock.MagicMock:
        path = urlparse(url).path
        body = routes[path]
        if isinstance(body, list):
            index = min(state.get(path, 0), len(body) - 1)
            state[path] = index + 1
            return _response(body[index])
        return _response(body)

    mock_session.return_value.get.side_effect = get


def _requested_urls(mock_session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in mock_session.return_value.get.call_args_list]


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

    def test_org_slugs_deduped_in_order(self):
        assert org_slugs_from_projects(["gh/a/one", "gh/a/two", "bb/b/three"]) == ["gh/a", "bb/b"]


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
    @mock.patch(PATCH_SESSION)
    def test_bad_slug_format_short_circuits_without_network(self, mock_session):
        is_valid, error = validate_credentials("token", "not-a-slug")

        assert is_valid is False
        assert error is not None and "not-a-slug" in error
        mock_session.return_value.get.assert_not_called()

    @mock.patch(PATCH_SESSION)
    def test_empty_slugs_rejected(self, mock_session):
        is_valid, error = validate_credentials("token", "  ")

        assert is_valid is False
        assert error is not None
        mock_session.return_value.get.assert_not_called()

    @parameterized.expand(
        [
            (401, None, False),
            (200, 404, False),
            (200, 403, False),
            (200, 200, True),
        ]
    )
    @mock.patch(PATCH_SESSION)
    def test_status_mapping(self, me_status, project_status, expected, mock_session):
        responses = [_response({}, status_code=me_status)]
        if project_status is not None:
            responses.append(_response(_page([], None), status_code=project_status))
        mock_session.return_value.get.side_effect = responses

        is_valid, error = validate_credentials("token", "gh/posthog/posthog")

        assert is_valid is expected
        assert (error is None) is expected

    @mock.patch(PATCH_SESSION)
    def test_probes_every_project_and_names_the_broken_one(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=200),  # /me
            _response(_page([], None), status_code=200),  # first project ok
            _response({}, status_code=404),  # second project missing
        ]

        is_valid, error = validate_credentials("token", "gh/posthog/posthog, gh/posthog/nope")

        assert is_valid is False
        assert error is not None and "gh/posthog/nope" in error

    @mock.patch(PATCH_SESSION)
    def test_swallows_connection_errors(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("token", "gh/posthog/posthog")

        assert is_valid is False
        assert error is not None

    @mock.patch(PATCH_SESSION)
    def test_sends_circle_token_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("token", "gh/posthog/posthog")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Circle-Token"] == "token"


class TestWorkflowMetricsRows:
    @mock.patch(PATCH_SESSION)
    def test_paginates_and_injects_project_slug_across_projects(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": [
                    _page([{"name": "ci"}], "token-2"),
                    _page([{"name": "release"}], None),
                ],
                "/api/v2/insights/gh/a/two/workflows": _page([{"name": "deploy"}], None),
            },
        )

        manager = _make_manager()
        batches = list(get_rows("token", "gh/a/one, gh/a/two", "workflow_metrics", mock.MagicMock(), manager))
        rows = _rows(batches)

        assert [(row["project_slug"], row["name"]) for row in rows] == [
            ("gh/a/one", "ci"),
            ("gh/a/one", "release"),
            ("gh/a/two", "deploy"),
        ]
        first_url = _requested_urls(mock_session)[0]
        assert parse_qs(urlparse(first_url).query)["reporting-window"] == ["last-90-days"]
        second_url = _requested_urls(mock_session)[1]
        assert parse_qs(urlparse(second_url).query)["page-token"] == ["token-2"]

    @mock.patch(PATCH_SESSION)
    def test_reporting_window_and_all_branches_passed_through(self, mock_session):
        _route_session(mock_session, {"/api/v2/insights/gh/a/one/workflows": _page([], None)})

        manager = _make_manager()
        list(
            get_rows(
                "token",
                "gh/a/one",
                "workflow_metrics",
                mock.MagicMock(),
                manager,
                reporting_window="last-7-days",
                all_branches=True,
            )
        )

        query = parse_qs(urlparse(_requested_urls(mock_session)[0]).query)
        assert query["reporting-window"] == ["last-7-days"]
        assert query["all-branches"] == ["true"]

    @mock.patch(PATCH_SESSION)
    def test_state_saved_after_each_page_and_on_project_completion(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": [
                    _page([{"name": "ci"}], "token-2"),
                    _page([{"name": "release"}], None),
                ]
            },
        )

        manager = _make_manager()
        rows = get_rows("token", "gh/a/one", "workflow_metrics", mock.MagicMock(), manager)

        next(rows)
        manager.save_state.assert_not_called()
        next(rows)
        saved = manager.save_state.call_args.args[0]
        assert saved.next_page_token == "token-2"
        with pytest.raises(StopIteration):
            next(rows)
        final = manager.save_state.call_args.args[0]
        assert final.slug == "gh/a/one"
        assert final.slug_done is True

    @mock.patch(PATCH_SESSION)
    def test_resume_skips_completed_project(self, mock_session):
        _route_session(mock_session, {"/api/v2/insights/gh/a/two/workflows": _page([{"name": "deploy"}], None)})

        manager = _make_manager(CircleciInsightsResumeConfig(slug="gh/a/one", slug_done=True))
        batches = list(get_rows("token", "gh/a/one, gh/a/two", "workflow_metrics", mock.MagicMock(), manager))

        assert [row["project_slug"] for row in _rows(batches)] == ["gh/a/two"]
        assert all("gh/a/one" not in url for url in _requested_urls(mock_session))

    @mock.patch(PATCH_SESSION)
    def test_resume_mid_project_starts_at_saved_token(self, mock_session):
        _route_session(mock_session, {"/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None)})

        manager = _make_manager(CircleciInsightsResumeConfig(slug="gh/a/one", next_page_token="resume-token"))
        list(get_rows("token", "gh/a/one", "workflow_metrics", mock.MagicMock(), manager))

        first_url = _requested_urls(mock_session)[0]
        assert parse_qs(urlparse(first_url).query)["page-token"] == ["resume-token"]

    @mock.patch(PATCH_SESSION)
    def test_resume_with_unknown_slug_starts_over(self, mock_session):
        _route_session(mock_session, {"/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None)})

        manager = _make_manager(CircleciInsightsResumeConfig(slug="gh/gone/away", next_page_token="stale"))
        batches = list(get_rows("token", "gh/a/one", "workflow_metrics", mock.MagicMock(), manager))

        assert [row["name"] for row in _rows(batches)] == ["ci"]
        first_url = _requested_urls(mock_session)[0]
        assert "page-token" not in parse_qs(urlparse(first_url).query)

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown CircleCI Insights endpoint"):
            list(get_rows("token", "gh/a/one", "nope", mock.MagicMock(), _make_manager()))


class TestWorkflowRunsFanOut:
    @mock.patch(PATCH_SESSION)
    def test_runs_fetched_per_discovered_workflow_with_parent_fields(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}, {"name": "release"}], None),
                "/api/v2/insights/gh/a/one/workflows/ci": _page(
                    [{"id": "r1", "created_at": "2026-07-01T00:00:00Z"}], None
                ),
                "/api/v2/insights/gh/a/one/workflows/release": _page(
                    [{"id": "r2", "created_at": "2026-07-02T00:00:00Z"}], None
                ),
            },
        )

        batches = list(get_rows("token", "gh/a/one", "workflow_runs", mock.MagicMock(), _make_manager()))
        rows = _rows(batches)

        assert [(row["id"], row["project_slug"], row["workflow_name"]) for row in rows] == [
            ("r1", "gh/a/one", "ci"),
            ("r2", "gh/a/one", "release"),
        ]

    @mock.patch(PATCH_SESSION)
    def test_incremental_passes_start_date_to_run_pages_only(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/gh/a/one/workflows/ci": _page([], None),
            },
        )

        list(
            get_rows(
                "token",
                "gh/a/one",
                "workflow_runs",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            )
        )

        urls = _requested_urls(mock_session)
        discovery_query = parse_qs(urlparse(urls[0]).query)
        runs_query = parse_qs(urlparse(urls[1]).query)
        # Discovery always scans the full retention window so no workflow is missed.
        assert discovery_query["reporting-window"] == ["last-90-days"]
        assert "start-date" not in discovery_query
        assert runs_query["start-date"] == ["2026-07-01"]

    @mock.patch(PATCH_SESSION)
    def test_full_refresh_sends_no_start_date(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/gh/a/one/workflows/ci": _page([], None),
            },
        )

        list(get_rows("token", "gh/a/one", "workflow_runs", mock.MagicMock(), _make_manager()))

        runs_query = parse_qs(urlparse(_requested_urls(mock_session)[1]).query)
        assert "start-date" not in runs_query

    @mock.patch(PATCH_SESSION)
    def test_resume_mid_workflow_skips_earlier_workflows(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page(
                    [{"name": "ci"}, {"name": "release"}, {"name": "deploy"}], None
                ),
                "/api/v2/insights/gh/a/one/workflows/release": _page([{"id": "r2"}], None),
                "/api/v2/insights/gh/a/one/workflows/deploy": _page([{"id": "r3"}], None),
            },
        )

        manager = _make_manager(
            CircleciInsightsResumeConfig(slug="gh/a/one", workflow_name="release", next_page_token="wf-token")
        )
        batches = list(get_rows("token", "gh/a/one", "workflow_runs", mock.MagicMock(), manager))

        assert [row["id"] for row in _rows(batches)] == ["r2", "r3"]
        assert any(url.endswith("release?page-token=wf-token") for url in _requested_urls(mock_session))
        # Workflows after the resume point start from their first page.
        deploy_urls = [url for url in _requested_urls(mock_session) if "/workflows/deploy" in url]
        assert "page-token" not in parse_qs(urlparse(deploy_urls[0]).query)

    @mock.patch(PATCH_SESSION)
    def test_state_saved_with_workflow_position(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/gh/a/one/workflows/ci": [
                    _page([{"id": "r1"}], "run-token-2"),
                    _page([{"id": "r2"}], None),
                ],
            },
        )

        manager = _make_manager()
        list(get_rows("token", "gh/a/one", "workflow_runs", mock.MagicMock(), manager))

        mid_save = manager.save_state.call_args_list[0].args[0]
        assert mid_save.slug == "gh/a/one"
        assert mid_save.workflow_name == "ci"
        assert mid_save.next_page_token == "run-token-2"


class TestJobMetricsFanOut:
    @mock.patch(PATCH_SESSION)
    def test_job_rows_carry_parents_and_reporting_window(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/gh/a/one/workflows/ci/jobs": _page([{"name": "build"}, {"name": "test"}], None),
            },
        )

        batches = list(
            get_rows(
                "token", "gh/a/one", "job_metrics", mock.MagicMock(), _make_manager(), reporting_window="last-30-days"
            )
        )
        rows = _rows(batches)

        assert [(row["project_slug"], row["workflow_name"], row["name"]) for row in rows] == [
            ("gh/a/one", "ci", "build"),
            ("gh/a/one", "ci", "test"),
        ]
        jobs_url = next(url for url in _requested_urls(mock_session) if "/jobs" in url)
        assert parse_qs(urlparse(jobs_url).query)["reporting-window"] == ["last-30-days"]


class TestJobTimeseriesFanOut:
    @mock.patch(PATCH_SESSION)
    def test_buckets_carry_parents_and_request_daily_granularity(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/time-series/gh/a/one/workflows/ci/jobs": _page(
                    [
                        {"name": "build", "timestamp": "2026-07-01T00:00:00Z"},
                        {"name": "test", "timestamp": "2026-07-01T00:00:00Z"},
                    ],
                    None,
                ),
            },
        )

        batches = list(get_rows("token", "gh/a/one", "job_timeseries", mock.MagicMock(), _make_manager()))
        rows = _rows(batches)

        assert [(row["project_slug"], row["workflow_name"], row["name"], row["timestamp"]) for row in rows] == [
            ("gh/a/one", "ci", "build", "2026-07-01T00:00:00Z"),
            ("gh/a/one", "ci", "test", "2026-07-01T00:00:00Z"),
        ]
        timeseries_url = next(url for url in _requested_urls(mock_session) if "time-series" in url)
        query = parse_qs(urlparse(timeseries_url).query)
        # Hourly buckets are only retained for 48 hours, so a scheduled sync must ask for daily.
        assert query["granularity"] == ["daily"]
        assert "reporting-window" not in query

    @mock.patch(PATCH_SESSION)
    def test_all_branches_widens_discovery_but_not_the_timeseries_request(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/time-series/gh/a/one/workflows/ci/jobs": _page([], None),
            },
        )

        logger = mock.MagicMock()
        list(get_rows("token", "gh/a/one", "job_timeseries", logger, _make_manager(), all_branches=True))

        urls = _requested_urls(mock_session)
        assert parse_qs(urlparse(urls[0]).query)["all-branches"] == ["true"]
        assert "all-branches" not in parse_qs(urlparse(urls[1]).query)
        # The setting silently cannot reach these rows, so the sync log has to say so.
        assert "default branch only" in logger.warning.call_args.args[0]

    @parameterized.expand([(True, ["2026-07-01T00:00:00Z"]), (False, None)])
    @mock.patch(PATCH_SESSION)
    def test_start_date_sent_only_on_incremental(self, incremental, expected, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/time-series/gh/a/one/workflows/ci/jobs": _page([], None),
            },
        )

        list(
            get_rows(
                "token",
                "gh/a/one",
                "job_timeseries",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=incremental,
                db_incremental_field_last_value=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            )
        )

        query = parse_qs(urlparse(_requested_urls(mock_session)[1]).query)
        assert query.get("start-date") == expected


class TestWorkflowSummaryFanOut:
    @mock.patch(PATCH_SESSION)
    def test_one_row_per_workflow_keeping_metrics_and_trends(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}, {"name": "release"}], None),
                "/api/v2/insights/gh/a/one/workflows/ci/summary": {
                    "metrics": {"total_runs": 10},
                    "trends": {"total_runs": 1.5},
                    "workflow_names": ["ci", "release"],
                },
                "/api/v2/insights/gh/a/one/workflows/release/summary": {
                    "metrics": {"total_runs": 2},
                    "trends": {"total_runs": 0.5},
                    "workflow_names": ["ci", "release"],
                },
            },
        )

        batches = list(get_rows("token", "gh/a/one", "workflow_summary", mock.MagicMock(), _make_manager()))

        # workflow_names describes the project rather than the row, so it is dropped.
        assert _rows(batches) == [
            {
                "project_slug": "gh/a/one",
                "workflow_name": "ci",
                "metrics": {"total_runs": 10},
                "trends": {"total_runs": 1.5},
            },
            {
                "project_slug": "gh/a/one",
                "workflow_name": "release",
                "metrics": {"total_runs": 2},
                "trends": {"total_runs": 0.5},
            },
        ]

    @mock.patch(PATCH_SESSION)
    def test_state_saved_per_workflow_and_resume_skips_earlier_ones(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page(
                    [{"name": "ci"}, {"name": "release"}, {"name": "deploy"}], None
                ),
                "/api/v2/insights/gh/a/one/workflows/release/summary": {"metrics": {}, "trends": {}},
                "/api/v2/insights/gh/a/one/workflows/deploy/summary": {"metrics": {}, "trends": {}},
            },
        )

        manager = _make_manager(CircleciInsightsResumeConfig(slug="gh/a/one", workflow_name="release"))
        batches = list(get_rows("token", "gh/a/one", "workflow_summary", mock.MagicMock(), manager))

        assert [row["workflow_name"] for row in _rows(batches)] == ["release", "deploy"]
        assert all("/workflows/ci/summary" not in url for url in _requested_urls(mock_session))
        saved_workflows = [call.args[0].workflow_name for call in manager.save_state.call_args_list]
        assert saved_workflows[:2] == ["release", "deploy"]


class TestWorkflowTestMetricsFanOut:
    @mock.patch(PATCH_SESSION)
    def test_merges_the_two_test_lists_on_test_identity(self, mock_session):
        shared = {"job_name": "test", "classname": "suite.A", "test_name": "t1", "failed_runs": 4, "p95_duration": 9.0}
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/gh/a/one/workflows/ci/test-metrics": {
                    "average_test_count": 12,
                    "most_failed_tests": [shared],
                    "slowest_tests": [
                        shared,
                        {"job_name": "test", "classname": "suite.B", "test_name": "t2", "p95_duration": 30.0},
                    ],
                },
            },
        )

        batches = list(get_rows("token", "gh/a/one", "workflow_test_metrics", mock.MagicMock(), _make_manager()))
        rows = _rows(batches)

        # The same test appears in both lists; the delta merge only dedupes across syncs, so a
        # duplicate here would seed duplicate rows under the composite primary key.
        assert [(row["classname"], row["test_name"]) for row in rows] == [("suite.A", "t1"), ("suite.B", "t2")]
        assert all(row["project_slug"] == "gh/a/one" and row["workflow_name"] == "ci" for row in rows)

    @mock.patch(PATCH_SESSION)
    def test_no_tests_reported_yields_nothing(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], None),
                "/api/v2/insights/gh/a/one/workflows/ci/test-metrics": {"average_test_count": 0},
            },
        )

        assert list(get_rows("token", "gh/a/one", "workflow_test_metrics", mock.MagicMock(), _make_manager())) == []


class TestBranchesRows:
    @mock.patch(PATCH_SESSION)
    def test_branch_names_become_rows_with_project_identifiers(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/branches": {
                    "org_id": "org-1",
                    "project_id": "proj-1",
                    "branches": ["master", "feature/x", "", None],
                }
            },
        )

        batches = list(get_rows("token", "gh/a/one", "branches", mock.MagicMock(), _make_manager()))

        assert _rows(batches) == [
            {"project_slug": "gh/a/one", "branch": "master", "org_id": "org-1", "project_id": "proj-1"},
            {"project_slug": "gh/a/one", "branch": "feature/x", "org_id": "org-1", "project_id": "proj-1"},
        ]

    @mock.patch(PATCH_SESSION)
    def test_unexpected_shape_syncs_zero_rows(self, mock_session):
        _route_session(mock_session, {"/api/v2/insights/gh/a/one/branches": {"message": "no insights"}})
        logger = mock.MagicMock()

        assert list(get_rows("token", "gh/a/one", "branches", logger, _make_manager())) == []
        logger.warning.assert_called_once()


class TestFlakyTestsRows:
    @mock.patch(PATCH_SESSION)
    def test_unwraps_envelope_and_injects_project_slug(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/one/flaky-tests": {
                    "flaky_tests": [{"test_name": "t1", "classname": "c", "job_name": "j", "workflow_name": "w"}],
                    "total_flaky_tests": 1,
                }
            },
        )

        batches = list(get_rows("token", "gh/a/one", "flaky_tests", mock.MagicMock(), _make_manager()))
        rows = _rows(batches)

        assert rows == [
            {
                "test_name": "t1",
                "classname": "c",
                "job_name": "j",
                "workflow_name": "w",
                "project_slug": "gh/a/one",
            }
        ]

    @mock.patch(PATCH_SESSION)
    def test_no_flaky_tests_yields_nothing(self, mock_session):
        _route_session(
            mock_session, {"/api/v2/insights/gh/a/one/flaky-tests": {"flaky_tests": [], "total_flaky_tests": 0}}
        )

        assert list(get_rows("token", "gh/a/one", "flaky_tests", mock.MagicMock(), _make_manager())) == []


class TestOrgSummaryRows:
    @mock.patch(PATCH_SESSION)
    def test_projects_collapse_to_one_org_fetch(self, mock_session):
        _route_session(
            mock_session,
            {
                "/api/v2/insights/gh/a/summary": {
                    "org_data": {"metrics": {}},
                    "org_project_data": [{"project_name": "one"}, {"project_name": "two"}],
                }
            },
        )

        batches = list(
            get_rows("token", "gh/a/one, gh/a/two", "org_summary_metrics", mock.MagicMock(), _make_manager())
        )
        rows = _rows(batches)

        assert [(row["org_slug"], row["project_name"]) for row in rows] == [("gh/a", "one"), ("gh/a", "two")]
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(PATCH_SESSION)
    def test_unexpected_shape_syncs_zero_rows(self, mock_session):
        _route_session(mock_session, {"/api/v2/insights/gh/a/summary": {"message": "no insights"}})
        logger = mock.MagicMock()

        batches = list(get_rows("token", "gh/a/one", "org_summary_metrics", logger, _make_manager()))

        assert batches == []
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

    @mock.patch(PATCH_SESSION)
    def test_5xx_retries_then_succeeds(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=503),
            _response(_page([{"name": "ci"}], None)),
        ]

        batches = list(get_rows("token", "gh/a/one", "workflow_metrics", mock.MagicMock(), _make_manager()))

        assert [row["name"] for row in _rows(batches)] == ["ci"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.circleci_insights.MAX_RETRIES",
        2,
    )
    @mock.patch(PATCH_SESSION)
    def test_persistent_5xx_raises_after_max_retries(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=500)

        with pytest.raises(CircleciInsightsRetryableError):
            list(get_rows("token", "gh/a/one", "workflow_metrics", mock.MagicMock(), _make_manager()))

    @mock.patch(PATCH_SESSION)
    def test_4xx_raises_immediately(self, mock_session):
        response = _response({}, status_code=401)
        response.raise_for_status.side_effect = Exception("401 Client Error")
        mock_session.return_value.get.return_value = response

        with pytest.raises(Exception, match="401 Client Error"):
            list(get_rows("token", "gh/a/one", "workflow_metrics", mock.MagicMock(), _make_manager()))

        assert mock_session.return_value.get.call_count == 1


class TestPageCap:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.circleci_insights.MAX_METRIC_PAGES",
        2,
    )
    @mock.patch(PATCH_SESSION)
    def test_page_cap_stops_pagination_and_logs(self, mock_session):
        _route_session(mock_session, {"/api/v2/insights/gh/a/one/workflows": _page([{"name": "ci"}], "always-more")})
        logger = mock.MagicMock()

        batches = list(get_rows("token", "gh/a/one", "workflow_metrics", logger, _make_manager()))

        assert len(batches) == 2
        logger.warning.assert_called_once()
        assert "page cap" in logger.warning.call_args.args[0]


class TestCircleciInsightsSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CIRCLECI_INSIGHTS_ENDPOINTS[endpoint]
        response = circleci_insights_source("token", "gh/a/one", endpoint, mock.MagicMock(), _make_manager())

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
        response = circleci_insights_source("token", "gh/a/one", endpoint, mock.MagicMock(), _make_manager())
        assert response.sort_mode == "desc"
