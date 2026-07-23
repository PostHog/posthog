from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest, _create_event, flush_persons_and_events
from unittest import mock

from django.utils import timezone

from parameterized import parameterized

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import MetricQuality, PRLifecycleEventKind, PRState
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _pr_row,
    _run_row,
    connect_github_source_without_data,
)
from products.engineering_analytics.backend.tests._logic_helpers import (
    _PR_LIST,
    _RUN_QUERY,
    _ago,
    _dt,
    _EndpointsWarehouseMixin,
    _header,
    _job_row,
    _pr_list_run,
    _resp,
    _WarehouseMixin,
)


class TestPRLifecycleMapping(BaseTest):
    """HogQL parsing (parse_select runs for real) plus row mapping and event
    assembly, without touching object storage. The query helper is mocked, so a GitHub
    source is connected (ORM only) just to satisfy the resolver."""

    def setUp(self) -> None:
        super().setUp()
        connect_github_source_without_data(self.team)

    def test_assembles_ordered_events_and_marks_partial(self) -> None:
        header = _header("merged", merged_at=_dt("2026-01-12T15:00:00"))
        runs = [(2001, "CI", "completed", "success", _dt("2026-01-11T09:00:00"), _dt("2026-01-11T12:00:00"))]
        with mock.patch(_RUN_QUERY, side_effect=[_resp([header]), _resp(runs)]):
            lifecycle = api.get_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

        assert lifecycle is not None
        assert lifecycle.metric_quality == MetricQuality.PARTIAL
        assert lifecycle.pull_request.state == PRState.MERGED
        assert lifecycle.pull_request.author.handle == "alice"
        assert lifecycle.pull_request.author.is_bot is False
        assert lifecycle.pull_request.repo.owner == "PostHog" and lifecycle.pull_request.repo.name == "posthog"
        assert [e.kind for e in lifecycle.events] == [
            PRLifecycleEventKind.OPENED,
            PRLifecycleEventKind.CI_STARTED,
            PRLifecycleEventKind.CI_FINISHED,
            PRLifecycleEventKind.MERGED,
        ]
        assert [e.run_id for e in lifecycle.events] == [None, 2001, 2001, None]

    def test_skips_events_with_null_timestamps(self) -> None:
        # parseDateTimeBestEffort yields NULL on a malformed/missing timestamp, so an event's `at`
        # can come back None. A single bad run timestamp must drop just that event, not raise and
        # take down the whole PR's lifecycle (the contract's `at` is non-nullable, and the event
        # sort can't order a None key).
        header = _header("merged", merged_at=_dt("2026-01-12T15:00:00"))
        runs = [
            # null start -> CI_STARTED dropped, but the completed finish still lands
            (2001, "CI", "completed", "success", None, _dt("2026-01-11T12:00:00")),
            # both timestamps null -> both events dropped
            (2002, "Deploy", "completed", "success", None, None),
        ]
        with mock.patch(_RUN_QUERY, side_effect=[_resp([header]), _resp(runs)]):
            lifecycle = api.get_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

        assert lifecycle is not None
        assert [e.kind for e in lifecycle.events] == [
            PRLifecycleEventKind.OPENED,
            PRLifecycleEventKind.CI_FINISHED,
            PRLifecycleEventKind.MERGED,
        ]
        assert [e.run_id for e in lifecycle.events] == [None, 2001, None]

    def test_returns_none_when_not_found(self) -> None:
        with mock.patch(_RUN_QUERY, return_value=_resp([])):
            assert api.get_pr_lifecycle(team=self.team, pr_number=999, repo="PostHog/posthog") is None

    @parameterized.expand(["PostHog", "PostHog/", "/posthog", "/"])
    def test_malformed_repo_raises_before_querying(self, repo: str) -> None:
        # A half-specified repo must fail loudly, not silently drop the filter and
        # return a PR from the wrong repo. Raises in _split_repo before any query.
        with self.assertRaises(ValueError):
            api.get_pr_lifecycle(team=self.team, pr_number=10, repo=repo)

    def test_passes_through_view_derived_fields(self) -> None:
        # is_bot and state come from the curated query as columns; the logic layer does not re-derive them.
        header = _header("closed", merged_at=None, closed_at=_dt("2026-01-12T15:00:00"), is_bot=True, head_sha="")
        with mock.patch(_RUN_QUERY, return_value=_resp([header])):
            lifecycle = api.get_pr_lifecycle(team=self.team, pr_number=10, repo="PostHog/posthog")

        assert lifecycle is not None
        assert lifecycle.pull_request.state == PRState.CLOSED
        assert lifecycle.pull_request.author.is_bot is True
        assert [e.kind for e in lifecycle.events] == [PRLifecycleEventKind.OPENED, PRLifecycleEventKind.CLOSED]


class TestPullRequestEndpointMapping(BaseTest):
    """Row mapping for the aggregate endpoints (the query method mocked, no warehouse).
    A GitHub source is connected (ORM only) so the resolver succeeds before the mocked
    query runs."""

    def setUp(self) -> None:
        super().setUp()
        connect_github_source_without_data(self.team)

    def test_ci_cards_maps_counts(self) -> None:
        with mock.patch(_RUN_QUERY, return_value=_resp([(5, 2, 1, 1)])):
            cards = api.get_ci_cards(team=self.team)
        assert (cards.open_prs, cards.repos, cards.stuck, cards.failing_ci) == (5, 2, 1, 1)

    def test_pull_request_list_maps_row(self) -> None:
        row = (
            10,
            "PR 10",
            "PostHog",
            "posthog",
            "alice",
            "https://avatars/alice",
            False,
            "open",
            False,
            _dt("2026-01-10T09:00:00"),
            None,
            None,
            ["bug", "p1"],
            3,
            2,
            1,
            0,
            ["E2E CI"],
            5,
            2,
        )
        # The query returns newest-first (its per-PR LIMIT BY keeps the most recent pushes); the mapper
        # reverses to the oldest-first contract, so the mock is ordered newest-first to match.
        push_rows = [
            ("PostHog", "posthog", 10, "sha-new", _dt("2026-01-11T10:00:00"), None, 0, 1),
            ("PostHog", "posthog", 10, "sha-old", _dt("2026-01-10T10:00:00"), 900, 1, 0),
        ]
        with mock.patch(_RUN_QUERY, side_effect=_pr_list_run([row], push_rows)):
            result = api.list_pull_requests(team=self.team, date_from="-30d")

        assert result.truncated is False
        assert len(result.items) == 1
        item = result.items[0]
        assert item.number == 10
        assert item.author.handle == "alice" and item.author.is_bot is False
        assert item.repo.owner == "PostHog" and item.repo.name == "posthog"
        assert item.state == PRState.OPEN
        assert item.labels == ["bug", "p1"]
        assert item.open_to_merge_seconds is None
        assert (item.ci.runs, item.ci.passing, item.ci.failing, item.ci.pending) == (3, 2, 1, 0)
        assert item.ci.failing_workflows == ["E2E CI"]
        assert (item.pushes, item.rerun_cycles) == (5, 2)
        assert item.estimated_cost_usd is None
        assert [(p.head_sha, p.wall_seconds, p.failed, p.pending) for p in item.push_history] == [
            ("sha-old", 900, True, False),
            ("sha-new", None, False, True),
        ]

    def test_pull_request_list_flags_truncation(self) -> None:
        # Cap patched low; return more rows than the cap to exercise the N+1 overflow
        # detection — the list reports truncated instead of silently dropping the tail.
        row = (
            10,
            "PR 10",
            "PostHog",
            "posthog",
            "alice",
            "https://avatars/alice",
            False,
            "open",
            False,
            _dt("2026-01-10T09:00:00"),
            None,
            None,
            ["bug"],
            0,
            0,
            0,
            0,
            list[str](),
            0,
            0,
        )
        with (
            mock.patch(f"{_PR_LIST}._LIMIT", 2),
            mock.patch(_RUN_QUERY, side_effect=_pr_list_run([row, row, row])),
        ):
            result = api.list_pull_requests(team=self.team, date_from="-30d")

        assert result.truncated is True
        assert result.limit == 2
        assert len(result.items) == 2


class TestResolveBranchMapping(BaseTest):
    """Row mapping for resolve_branch (query method mocked, no warehouse). A GitHub source is
    connected (ORM only) so the resolver succeeds before the mocked query runs."""

    def setUp(self) -> None:
        super().setUp()
        connect_github_source_without_data(self.team)

    def test_maps_rows_and_normalizes_empty_fields(self) -> None:
        # branch columns: repo_owner, repo_name, number, title, state. The second row carries an empty
        # title / null state -> both normalize to None.
        rows = [("PostHog", "posthog", 42, "Fix bug", "merged"), ("PostHog", "posthog", 7, "", None)]
        with mock.patch(_RUN_QUERY, return_value=_resp(rows)) as run:
            matches = api.resolve_branch(team=self.team, branch="feat/x")
        assert [(m.repo, m.number, m.title, m.state) for m in matches] == [
            ("PostHog/posthog", 42, "Fix bug", "merged"),
            ("PostHog/posthog", 7, None, None),
        ]
        assert run.call_count == 1

    @parameterized.expand([("branch_none", None), ("branch_blank", "   ")])
    def test_rejects_missing_branch(self, _name: str, branch: str | None) -> None:
        # Validation raises before any query is issued (source resolution still succeeds first).
        with mock.patch(_RUN_QUERY) as run, self.assertRaises(ValueError):
            api.resolve_branch(team=self.team, branch=branch)
        run.assert_not_called()


class TestPullRequestEndpointsWarehouse(_EndpointsWarehouseMixin, BaseTest):
    """PR-scoped end-to-end aggregates over the shared seeded warehouse tables."""

    def test_ci_cards_counts(self) -> None:
        self._seed()
        cards = api.get_ci_cards(team=self.team)
        assert cards.open_prs == 5  # 10, 11, 12, 13, 16
        assert cards.repos == 1  # all PostHog/posthog
        assert cards.stuck == 1  # only 11 (10 recent, 12 draft, 13 and 16 bots)
        assert cards.failing_ci == 1  # only 10 has a failing latest run

    def test_pull_request_list_window_and_rollup(self) -> None:
        self._seed()
        result = api.list_pull_requests(team=self.team)
        assert result.truncated is False
        by_number = {item.number: item for item in result.items}
        assert set(by_number) == {10, 11, 12, 13, 14, 16}  # 15 merged before the window
        assert by_number[10].ci.failing == 1
        assert by_number[11].ci.passing == 1
        assert by_number[13].author.is_bot is True  # '[bot]' suffix branch
        assert by_number[16].author.is_bot is True  # KNOWN_BOT_HANDLES allowlist branch
        # pushes = distinct head SHAs across runs attributed to the PR; rerun_cycles = 2nd+ attempts.
        assert (by_number[10].pushes, by_number[10].rerun_cycles) == (2, 1)
        assert (by_number[11].pushes, by_number[11].rerun_cycles) == (1, 0)
        assert by_number[12].pushes == 0  # no runs attributed to this PR
        assert by_number[10].estimated_cost_usd is None  # no jobs source seeded here → no cost figure

    def test_pull_request_list_includes_cost_when_jobs_synced(self) -> None:
        # With the jobs source synced, the list carries per-PR cost + billable minutes.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(70, "alice", "open", 0, _ago(1), head_sha="sha70")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(9400, "CI", "sha70", "completed", "success", _ago(1), _ago(1), pr_number=70)],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [_job_row(94000, 9400, "build", "success", labels='["depot-ubuntu-22.04-4"]')],
        )
        item = next(i for i in api.list_pull_requests(team=self.team).items if i.number == 70)
        assert item.estimated_cost_usd is not None and item.estimated_cost_usd > 0
        assert item.billable_minutes is not None and item.billable_minutes > 0

    def test_pr_cost_sums_all_jobs_past_the_default_row_cap(self) -> None:
        # A PR with more jobs than HogQL's default 100-row cap: the detail cost must sum every job, not
        # silently truncate to the first 100 (the truncation that made PR detail cost disagree with the list).
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(71, "alice", "open", 0, _ago(1), head_sha="sha71")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(9700, "CI", "sha71", "completed", "success", _ago(1), _ago(1), pr_number=71)],
        )
        job_count = 150
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(97000 + i, 9700, f"job-{i}", "success", labels='["depot-ubuntu-22.04-4"]')
                for i in range(job_count)
            ],
        )
        cost = api.get_pr_cost(team=self.team, pr_number=71, repo="PostHog/posthog")
        # Every job counts; before the LIMIT fix this capped at 100. 150 jobs x 120s = 300 min, depot
        # 4-core (2x) at $0.004/min = 300 x 0.004 x 2 = $2.40.
        assert cost.costed_jobs == job_count
        assert cost.estimated_cost_usd == pytest.approx(2.40)

    def test_pr_cost_clamps_clock_skewed_negative_durations(self) -> None:
        # Two jobs share one run/label group: a normal +120s job and a clock-skewed -120s one
        # (completed_at < started_at). The grouped sum must clamp the negative per-job (greatest(.,0))
        # so it doesn't cancel its group-mate's elapsed inside the group total. Without the clamp the
        # group sums to 0s and the PR reads $0.00; with it, the skewed job contributes 0 and the
        # normal job's 120s survives = 2 billable min, depot 4-core (2x) at $0.004/min = $0.016.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(72, "alice", "open", 0, _ago(1), head_sha="sha72")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(9800, "CI", "sha72", "completed", "success", _ago(1), _ago(1), pr_number=72)],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(98000, 9800, "ok", "success", started="2026-01-01 00:00:00", completed="2026-01-01 00:02:00"),
                _job_row(
                    98001, 9800, "skew", "success", started="2026-01-01 00:02:00", completed="2026-01-01 00:00:00"
                ),
            ],
        )
        cost = api.get_pr_cost(team=self.team, pr_number=72, repo="PostHog/posthog")
        assert cost.costed_jobs == 2
        assert cost.billable_minutes == pytest.approx(2.0)
        assert cost.estimated_cost_usd == pytest.approx(0.016)

    def test_pull_request_list_author_filter(self) -> None:
        # The author filter scopes the list to one author's PRs (drives the author page).
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(81, "alice", "open", 0, _ago(1), head_sha="sha81"),
                _pr_row(82, "bob", "open", 0, _ago(1), head_sha="sha82"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(8100, "CI", "sha81", "completed", "success", _ago(1), _ago(1), pr_number=81)],
        )
        assert {i.number for i in api.list_pull_requests(team=self.team, author="alice").items} == {81}
        assert {i.number for i in api.list_pull_requests(team=self.team, author="bob").items} == {82}

    def test_resolve_branch_orders_open_first(self) -> None:
        # The branch path matches the PR head ref (head.ref); open PRs come before merged/closed ones,
        # and PRs on other branches are excluded.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(62, "bob", "closed", 0, _ago(6), merged_at=_ago(1), head_sha="sha62", head_ref="feat/login"),
                _pr_row(61, "alice", "open", 0, _ago(2), head_sha="sha61", head_ref="feat/login"),
                _pr_row(63, "carol", "open", 0, _ago(1), head_sha="sha63", head_ref="other"),
            ],
        )
        # Source resolution requires the workflow_runs schema synced too (SPEC: both endpoints
        # required together), even though the branch path only reads the PR snapshot.
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])
        matches = api.resolve_branch(team=self.team, branch="feat/login")
        assert [m.number for m in matches] == [61, 62]  # only feat/login PRs, open first
        # A branch matching no PR resolves to nothing (empty list, not an error).
        assert api.resolve_branch(team=self.team, branch="feat/nothing") == []

    def test_resolve_branch_prefers_pr_active_at_timestamp(self) -> None:
        # Same head ref reused across PRs over time: an old one merged months ago and a newer open one.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(
                    70, "bob", "closed", 0, _ago(120), merged_at=_ago(110), head_sha="sha70", head_ref="feat/reuse"
                ),
                _pr_row(71, "alice", "open", 0, _ago(2), head_sha="sha71", head_ref="feat/reuse"),
            ],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])
        # No timestamp: open PR wins on the open-first/recency fallback.
        assert [m.number for m in api.resolve_branch(team=self.team, branch="feat/reuse")] == [71, 70]
        # A timestamp inside the old PR's lifetime window ranks it first, even though the newer PR is open.
        during_old = timezone.now() - timedelta(days=112)
        matches = api.resolve_branch(team=self.team, branch="feat/reuse", timestamp=during_old)
        assert [m.number for m in matches] == [70, 71]

    def test_pr_runs_span_all_commits(self) -> None:
        # The PR detail lists runs across all of the PR's commits (by association), not just head SHA.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(70, "alice", "open", 0, _ago(1), head_sha="shaA")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(9300, "CI", "shaA", "completed", "success", _ago(2), _ago(2), pr_number=70),
                _run_row(9301, "CI", "shaB", "completed", "failure", _ago(1), _ago(1), pr_number=70),
                _run_row(9302, "CI", "shaC", "completed", "success", _ago(1), _ago(1), pr_number=71),
            ],
        )
        runs = api.list_pr_runs(team=self.team, pr_number=70, repo="PostHog/posthog")
        assert {r.id for r in runs} == {9300, 9301}  # only PR 70's runs
        assert {r.head_sha for r in runs} == {"shaA", "shaB"}  # across two commits

    def test_pr_cost_aggregates_billable_jobs_across_runs(self) -> None:
        # PR cost sums the jobs of all the PR's runs (across commits), counting only billable Linux
        # runners; absent jobs source → graceful empty with jobs_available False.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(60, "alice", "open", 0, _ago(1), head_sha="sha60")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(9100, "CI", "sha60a", "completed", "success", _ago(2), _ago(2), pr_number=60),
                _run_row(9101, "CI", "sha60b", "completed", "failure", _ago(1), _ago(1), pr_number=60),
                _run_row(9102, "CI", "sha99", "completed", "success", _ago(1), _ago(1), pr_number=61),
            ],
        )
        # No jobs table synced yet → every figure zero/None, cards hidden.
        empty = api.get_pr_cost(team=self.team, pr_number=60, repo="PostHog/posthog")
        assert empty.jobs_available is False and empty.estimated_cost_usd is None and empty.billable_minutes == 0.0

        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                # Two billable Linux jobs across two of the PR's runs, plus a github-hosted (excluded).
                _job_row(91000, 9100, "build", "success", labels='["depot-ubuntu-22.04-4"]'),
                _job_row(91001, 9101, "test", "failure", labels='["depot-ubuntu-22.04-4"]'),
                _job_row(91002, 9101, "e2e", "success", labels='["ubuntu-latest"]'),
                # A job on another PR's run must not leak into PR 60's cost.
                _job_row(91003, 9102, "build", "success", labels='["depot-ubuntu-22.04-16"]'),
            ],
        )
        cost = api.get_pr_cost(team=self.team, pr_number=60, repo="PostHog/posthog")
        assert cost.jobs_available is True
        assert cost.costed_jobs == 2  # the two depot Linux jobs on PR 60's runs
        assert cost.excluded_jobs == 1  # the github-hosted one
        assert cost.estimated_cost_usd is not None and cost.estimated_cost_usd > 0
        assert cost.billable_minutes == pytest.approx(4.0)  # 2 jobs x 2 min each (_job_row default window)
        # Per-workflow breakdown sums to the same: PR 60's runs are all the "CI" workflow.
        ci_cost = next(w for w in cost.by_workflow if w.workflow_name == "CI")
        assert ci_cost.costed_jobs == 2 and ci_cost.excluded_jobs == 1
        # Per-run breakdown keys by (run_id, run_attempt): each of the two runs carries one billable job
        # (run 9101's github-hosted e2e is excluded from its minutes), summing back to the PR total.
        by_run = {rc.run_id: rc for rc in cost.by_run}
        assert by_run[9100].billable_minutes == pytest.approx(2.0)
        assert by_run[9101].billable_minutes == pytest.approx(2.0)
        assert sum(rc.billable_minutes for rc in cost.by_run) == pytest.approx(cost.billable_minutes)

    def test_pull_request_list_rollup_is_repo_qualified(self) -> None:
        # PR numbers restart per repo. Two repos share PR #10; the per-PR push / re-run rollup must
        # attribute each repo's runs to its own PR, not merge them on number alone. (The head-SHA CI
        # rollup is already repo-safe; this proves the runs_by_pr join is too.) A resolved source is
        # one repo today, so this is the defensive guarantee, exercised by seeding both into one.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(10, "alice", "open", 0, _ago(1), head_sha="sha10", full_name="PostHog/posthog"),
                _pr_row(10, "bob", "open", 0, _ago(1), head_sha="shaB10", full_name="PostHog/posthog.com"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(3001, "CI", "sha10", "completed", "success", _ago(1), _ago(1), pr_number=10),
                _run_row(
                    3002,
                    "CI",
                    "shaB10",
                    "completed",
                    "success",
                    _ago(1),
                    _ago(1),
                    pr_number=10,
                    full_name="PostHog/posthog.com",
                ),
                # A second push + re-run on the other repo's PR #10 — must not leak onto posthog's #10.
                _run_row(
                    3003,
                    "CI",
                    "shaB10b",
                    "completed",
                    "success",
                    _ago(1),
                    _ago(1),
                    pr_number=10,
                    run_attempt=2,
                    full_name="PostHog/posthog.com",
                ),
            ],
        )
        result = api.list_pull_requests(team=self.team)
        by_repo = {(item.repo.owner, item.repo.name): item for item in result.items}
        assert (by_repo[("PostHog", "posthog")].pushes, by_repo[("PostHog", "posthog")].rerun_cycles) == (1, 0)
        assert (by_repo[("PostHog", "posthog.com")].pushes, by_repo[("PostHog", "posthog.com")].rerun_cycles) == (2, 1)


class TestPRLLMSpendWarehouse(_WarehouseMixin, BaseTest):
    """LLM token spend attributed to a PR by git branch, over a real warehouse PR row plus
    $ai_generation events. Skips when object storage is unreachable."""

    def _generation(
        self,
        *,
        branch: str | None,
        days_ago: float,
        cost: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        repo: str | None = None,
        session: str | None = None,
        trace: str | None = None,
        event: str = "$ai_generation",
    ) -> None:
        # branch=None seeds an unstamped generation (no $ai_git_branch), the transient state the
        # carry-forward and prefix rules attribute; session/trace set the grouping key.
        props: dict[str, Any] = {
            "$ai_total_cost_usd": cost,
            "$ai_input_tokens": input_tokens,
            "$ai_output_tokens": output_tokens,
        }
        if branch is not None:
            props["$ai_git_branch"] = branch
        if repo is not None:
            props["$ai_git_repo"] = repo
        if session is not None:
            props["$ai_session_id"] = session
        if trace is not None:
            props["$ai_trace_id"] = trace
        _create_event(
            event=event,
            team=self.team,
            distinct_id="agent-1",
            properties=props,
            timestamp=timezone.now() - timedelta(days=days_ago),
        )

    def _seed_pr(self, number: int, head_ref: str, *, base_ref: str = "master") -> None:
        # A merged PR fixes the window to [created - 14d, merged] = [_ago(19), _ago(1)]. The runs table
        # must exist for the source to resolve even though LLM spend never reads it (mixin gotcha).
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(
                    number,
                    "alice",
                    "closed",
                    0,
                    _ago(5),
                    merged_at=_ago(1),
                    head_sha=f"sha{number}",
                    head_ref=head_ref,
                    base_ref=base_ref,
                )
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(number * 100, "CI", f"sha{number}", "completed", "success", _ago(4), _ago(4), pr_number=number)],
        )

    def test_llm_spend_attributes_by_branch_within_window(self) -> None:
        branch = "feat/tokens"
        self._seed_pr(80, branch)
        # Matches: on-branch, in-window; one with no repo stamped, one with the repo stamped in clone-URL
        # casing (the repo compare is case-insensitive, like GitHub repo names).
        self._generation(branch=branch, days_ago=4, cost=1.0, input_tokens=100, output_tokens=50)
        self._generation(
            branch=branch, days_ago=10, cost=2.0, input_tokens=200, output_tokens=80, repo="posthog/POSTHOG"
        )
        # Excluded: wrong repo, wrong branch, before the lead window, after merge, wrong event type.
        self._generation(branch=branch, days_ago=4, cost=99.0, repo="other/repo")
        self._generation(branch="other-branch", days_ago=4, cost=99.0)
        self._generation(branch=branch, days_ago=25, cost=99.0)
        self._generation(branch=branch, days_ago=0, cost=99.0)
        self._generation(branch=branch, days_ago=4, cost=99.0, event="$ai_embedding")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=80, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 2
        assert cost.llm_spend.cost_usd == pytest.approx(3.0)
        assert cost.llm_spend.input_tokens == 300
        assert cost.llm_spend.output_tokens == 130

    def test_llm_spend_none_when_head_is_base(self) -> None:
        self._seed_pr(84, "master", base_ref="master")
        self._generation(branch="master", days_ago=4, cost=5.0)
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=84, repo="PostHog/posthog")
        assert cost.llm_spend is None

    def test_llm_spend_failure_degrades_to_none(self) -> None:
        # The spend join is an optional enrichment; a query failure (e.g. a timeout on an AI-heavy
        # team) must not take the whole cost summary down with it.
        self._seed_pr(85, "feat/degrade")
        with mock.patch(
            "products.engineering_analytics.backend.logic.pull_requests.query_pr_llm_spend",
            side_effect=Exception("clickhouse timeout"),
        ):
            cost = api.get_pr_cost(team=self.team, pr_number=85, repo="PostHog/posthog")
        assert cost.llm_spend is None

    def test_llm_spend_none_when_no_generations(self) -> None:
        # Open PR whose branch no event carries — spend stays null so the UI hides the row.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(81, "alice", "open", 0, _ago(2), head_sha="sha81", head_ref="feat/empty")],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(8100, "CI", "sha81", "completed", "success", _ago(1), _ago(1), pr_number=81)],
        )
        cost = api.get_pr_cost(team=self.team, pr_number=81, repo="PostHog/posthog")
        assert cost.llm_spend is None

    @parameterized.expand(
        [
            # first feature stamp == H: the base-stamped prefix and the H events all credit H.
            ("first_feature_is_head", "feat/tokens", 4, pytest.approx(14.0)),
            # first feature stamp == a different branch: the prefix belongs to that branch, so only
            # the later direct-H stamp credits H (guards against prefix-stealing).
            ("first_feature_is_other", "feat/other", 1, pytest.approx(8.0)),
        ]
    )
    def test_prefix_credits_head_only_when_first_feature_branch_is_head(
        self, _name: str, first_feature: str, expected_generations: int, expected_cost: Any
    ) -> None:
        head = "feat/tokens"
        self._seed_pr(82, head, base_ref="master")
        # Same session: base-stamped exploration, then the first feature stamp, then a direct H stamp.
        self._generation(branch="master", days_ago=10, cost=1.0, session="s1")
        self._generation(branch="master", days_ago=9, cost=1.0, session="s1")
        self._generation(branch=first_feature, days_ago=8, cost=4.0, session="s1")
        self._generation(branch=head, days_ago=6, cost=8.0, session="s1")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=82, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == expected_generations
        assert cost.llm_spend.cost_usd == expected_cost

    def test_carry_forward_follows_latest_stamp_until_a_branch_switch(self) -> None:
        self._seed_pr(83, "feat/tokens", base_ref="master")
        # H stamp, then an unstamped event that carries H forward, then a switch to another branch whose
        # later unstamped event must NOT credit H.
        self._generation(branch="feat/tokens", days_ago=10, cost=1.0, session="s2")
        self._generation(branch=None, days_ago=9, cost=2.0, session="s2")
        self._generation(branch="feat/other", days_ago=8, cost=99.0, session="s2")
        self._generation(branch=None, days_ago=7, cost=99.0, session="s2")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=83, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 2
        assert cost.llm_spend.cost_usd == pytest.approx(3.0)

    def test_out_of_window_events_excluded_even_in_an_eligible_session(self) -> None:
        self._seed_pr(84, "feat/tokens", base_ref="master")
        # In-window H stamp makes the session eligible; an unstamped event after the merge would carry H
        # forward if the window were dropped from the group scan, so it guards that outer-window filter.
        self._generation(branch="feat/tokens", days_ago=4, cost=1.0, session="s3")
        self._generation(branch=None, days_ago=0, cost=99.0, session="s3")
        self._generation(branch="feat/tokens", days_ago=25, cost=99.0, session="s3")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=84, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 1
        assert cost.llm_spend.cost_usd == pytest.approx(1.0)

    def test_ungrouped_events_count_only_via_a_direct_head_stamp(self) -> None:
        self._seed_pr(85, "feat/tokens", base_ref="master")
        # No session and no trace id: no group, so neither prefix nor carry-forward applies — only the
        # event stamped H directly counts.
        self._generation(branch="feat/tokens", days_ago=8, cost=5.0)
        self._generation(branch="master", days_ago=9, cost=99.0)
        self._generation(branch=None, days_ago=7, cost=99.0)
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=85, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 1
        assert cost.llm_spend.cost_usd == pytest.approx(5.0)

    def test_session_with_only_base_stamps_is_not_eligible(self) -> None:
        self._seed_pr(86, "feat/tokens", base_ref="master")
        # A session that never stamps the head ref is not eligible, so its base-stamped exploration
        # credits nothing and spend stays null.
        self._generation(branch="master", days_ago=10, cost=99.0, session="s4")
        self._generation(branch=None, days_ago=9, cost=99.0, session="s4")
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=86, repo="PostHog/posthog")
        assert cost.llm_spend is None

    def test_newest_snapshot_by_updated_at_drives_attribution(self) -> None:
        # Two snapshot rows for the same PR share created_at (the PR's creation time); only updated_at
        # separates the stale row from the fresh one. The header must pick the freshest so its head_ref
        # — not the stale row's — drives the branch attribution. Ordering on created_at alone left the
        # winner arbitrary and could credit the stale branch.
        created = _ago(5)
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(90, "alice", "closed", 0, created, merged_at=_ago(3), head_sha="sha90a", head_ref="feat/stale"),
                _pr_row(90, "alice", "closed", 0, created, merged_at=_ago(1), head_sha="sha90b", head_ref="feat/fresh"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(9000, "CI", "sha90b", "completed", "success", _ago(4), _ago(4), pr_number=90)],
        )
        self._generation(branch="feat/fresh", days_ago=4, cost=3.0, input_tokens=30, output_tokens=10)
        self._generation(branch="feat/stale", days_ago=4, cost=99.0)
        flush_persons_and_events()

        cost = api.get_pr_cost(team=self.team, pr_number=90, repo="PostHog/posthog")
        assert cost.llm_spend is not None
        assert cost.llm_spend.generations == 1
        assert cost.llm_spend.cost_usd == pytest.approx(3.0)


class TestRecentlyMergedPullRequests(_WarehouseMixin, BaseTest):
    """The recently-merged discovery seam over real warehouse tables: only PRs merged at or after
    `since` in the scoped repo surface, each with its branch-tip head SHA. Skips when object storage
    is unreachable."""

    def test_returns_merged_prs_since_cutoff_scoped_to_repo(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                # merged within the window -> returned, carrying its branch-tip head SHA
                _pr_row(20, "alice", "closed", 0, _ago(7), merged_at=_ago(5), head_sha="sha20"),
                # open / never merged -> excluded by merged_at IS NOT NULL
                _pr_row(21, "bob", "open", 0, _ago(3), head_sha="sha21"),
                # merged before the cutoff -> excluded by merged_at >= since
                _pr_row(22, "carol", "closed", 0, _ago(40), merged_at=_ago(30), head_sha="sha22"),
                # merged in-window but a different repo -> excluded by the repo scope
                _pr_row(
                    23, "dave", "closed", 0, _ago(4), merged_at=_ago(3), head_sha="sha23", full_name="PostHog/other"
                ),
                # merged in-window -> returned unless a `numbers` scope excludes it
                _pr_row(24, "erin", "closed", 0, _ago(2), merged_at=_ago(1), head_sha="sha24"),
            ],
        )
        # workflow_runs is required for the source to resolve, though this read only touches PRs.
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(3001, "CI", "sha20", "completed", "success", _ago(5), _ago(5), pr_number=20)],
        )

        since = timezone.now() - timedelta(days=10)
        merged = api.list_recently_merged_pull_requests(team=self.team, repository="PostHog/posthog", since=since)
        assert [(pr.number, pr.head_sha) for pr in merged] == [(24, "sha24"), (20, "sha20")]

        # `numbers` scopes the lookup to the PRs a caller is waiting on, so a high-merge-volume repo
        # can't push them past the query's row ceiling.
        scoped = api.list_recently_merged_pull_requests(
            team=self.team, repository="PostHog/posthog", since=since, numbers=[20]
        )
        assert [pr.number for pr in scoped] == [20]
