from collections import defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    ComparisonTeamBasis as Basis,
    DeliveryScopeKind,
    PRTimelineSegmentKind as Kind,
    QueryWorkLimitExceededError,
    ScopeRepoFigure,
)
from products.engineering_analytics.backend.logic.census import CENSUS_EVENT
from products.engineering_analytics.backend.logic.comparison_teams import choose_comparison_teams
from products.engineering_analytics.backend.logic.delivery_scope import CI_LOOKBACK, DeliveryScope, SummaryScope
from products.engineering_analytics.backend.logic.merge_queue import GateAttempt
from products.engineering_analytics.backend.logic.pr_timeline import (
    MasterFailureIndex,
    PRTimelineBuilder,
    PRTimelineInput,
    Push,
    ReviewVerdict,
    RunAttempt,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.delivery_comparison import query_delivery_comparison
from products.engineering_analytics.backend.logic.queries.delivery_summary import (
    MergedPRFacts,
    _before_approval_share,
    _median_ready_to_first_approval,
    _median_ready_to_merge,
    _pushes_after_approval,
    query_delivery_summary,
    scope_repo_figure,
)
from products.engineering_analytics.backend.logic.queries.merge_queue_overview import query_merge_queue_overview
from products.engineering_analytics.backend.logic.queries.pull_request_timelines import query_pull_request_timelines
from products.engineering_analytics.backend.logic.views.source_schema import (
    DEPLOYMENT_STATUSES_COLUMNS,
    DEPLOYMENTS_COLUMNS,
    ISSUE_EVENTS_COLUMNS,
    PULL_REQUESTS_COLUMNS,
    REVIEWS_COLUMNS,
    TEAM_MEMBERS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _deployment_row,
    _issue_event_row,
    _pr_row,
    _run_row,
    _status_row,
    create_github_source,
)
from products.engineering_analytics.backend.tests._logic_helpers import (
    _ago,
    _ago_offset_with_duration,
    _dt,
    _job_row,
    _WarehouseMixin,
)

T0 = datetime(2026, 9, 1, 8, tzinfo=UTC)


def _at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def _attempt(
    sha: str,
    start: float,
    end: float | None,
    *,
    queued: float | None = None,
    workflow: str = "CI",
    failed: bool = False,
    succeeded: bool | None = None,
    attempt: int = 1,
    jobs: tuple[str, ...] = (),
) -> RunAttempt:
    return RunAttempt(
        run_id=1,
        workflow_name=workflow,
        head_sha=sha,
        attempt=attempt,
        queued_at=_at(start if queued is None else queued),
        started_at=_at(start),
        completed_at=_at(end) if end is not None else None,
        failed=failed,
        succeeded=(end is not None and not failed) if succeeded is None else succeeded,
        failed_jobs=jobs,
    )


def _pr(
    end: float,
    attempts: list[RunAttempt],
    *,
    reviews: list[ReviewVerdict] | None = None,
    gates: list[GateAttempt] | None = None,
    is_open: bool = False,
    is_merged: bool | None = None,
    is_draft: bool = False,
    trunk_out: bool = False,
    pushes: list[Push] | None = None,
) -> PRTimelineInput:
    pushes_by_sha: dict[str, list[datetime]] = defaultdict(list)
    for attempt in attempts:
        pushes_by_sha[attempt.head_sha].append(attempt.started_at)
    return PRTimelineInput(
        started_at=_at(0),
        ended_at=_at(end),
        is_open=is_open,
        is_merged=not is_open if is_merged is None else is_merged,
        is_draft=is_draft,
        pushes=pushes
        if pushes is not None
        else [Push(head_sha=sha, pushed_at=min(times)) for sha, times in pushes_by_sha.items()],
        attempts=attempts,
        gate_attempts=gates or [],
        reviews=reviews,
        trunk_out_of_queue=trunk_out,
    )


class TestPRTimelineBuilder(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "rerun_turns_red_green",
                _pr(
                    6,
                    [_attempt("a", 0, 1, failed=True), _attempt("a", 3, 4, attempt=2)],
                    reviews=[ReviewVerdict(reviewer="ada", state="APPROVED", submitted_at=_at(5))],
                ),
                [],
                [
                    (Kind.CI_RUNNING, 0, 1),
                    (Kind.RED_PASSED_ON_RERUN, 1, 3),
                    (Kind.CI_RUNNING, 3, 4),
                    (Kind.WAITING_FOR_REVIEW, 4, 5),
                    (Kind.APPROVED_NOT_ENQUEUED, 5, 6),
                ],
            ),
            (
                "cancelled_rerun_is_not_a_pass",
                _pr(5, [_attempt("a", 0, 1, failed=True), _attempt("a", 3, 4, attempt=2, succeeded=False)]),
                [],
                [
                    (Kind.CI_RUNNING, 0, 1),
                    (Kind.RED_NOT_PROVABLE, 1, 3),
                    (Kind.CI_RUNNING, 3, 4),
                    (Kind.REVIEW_STATE_UNKNOWN, 4, 5),
                ],
            ),
            (
                "queued_check_counts_as_ci",
                _pr(
                    4,
                    [_attempt("a", 1, 2, queued=0)],
                    reviews=[ReviewVerdict(reviewer="ada", state="APPROVED", submitted_at=_at(0))],
                    pushes=[Push(head_sha="a", pushed_at=_at(0))],
                ),
                [],
                [(Kind.CI_RUNNING, 0, 2), (Kind.APPROVED_NOT_ENQUEUED, 2, 4)],
            ),
            (
                "later_workflow_does_not_backfill_queue_time",
                _pr(
                    5,
                    [_attempt("a", 0, 1), _attempt("a", 3, 4, queued=2, workflow="Deploy")],
                    reviews=[ReviewVerdict(reviewer="ada", state="APPROVED", submitted_at=_at(0))],
                ),
                [],
                [
                    (Kind.CI_RUNNING, 0, 1),
                    (Kind.APPROVED_NOT_ENQUEUED, 1, 2),
                    (Kind.CI_RUNNING, 2, 4),
                    (Kind.APPROVED_NOT_ENQUEUED, 4, 5),
                ],
            ),
            (
                "rerun_does_not_backfill_queue_time",
                _pr(5, [_attempt("a", 0, 1, failed=True), _attempt("a", 3, 4, attempt=2)]),
                [],
                [
                    (Kind.CI_RUNNING, 0, 1),
                    (Kind.RED_PASSED_ON_RERUN, 1, 3),
                    (Kind.CI_RUNNING, 3, 4),
                    (Kind.REVIEW_STATE_UNKNOWN, 4, 5),
                ],
            ),
            (
                "later_push_ends_red",
                _pr(4, [_attempt("a", 0, 1, failed=True), _attempt("b", 2, 3)]),
                [],
                [
                    (Kind.CI_RUNNING, 0, 1),
                    (Kind.RED_FIXED_BY_PUSH, 1, 2),
                    (Kind.CI_RUNNING, 2, 3),
                    (Kind.REVIEW_STATE_UNKNOWN, 3, 4),
                ],
            ),
            (
                "same_job_failing_on_master",
                _pr(3, [_attempt("a", 0, 1, failed=True, jobs=("Backend tests (1/3)",))]),
                [("CI", "Backend tests (2/3)", _at(-2))],
                [(Kind.CI_RUNNING, 0, 1), (Kind.RED_MASTER_BROKEN, 1, 3)],
            ),
            (
                "master_failure_too_far_away",
                _pr(3, [_attempt("a", 0, 1, failed=True, jobs=("Backend tests (1/3)",))]),
                [("CI", "Backend tests (2/3)", _at(-20))],
                [(Kind.CI_RUNNING, 0, 1), (Kind.RED_NOT_PROVABLE, 1, 3)],
            ),
            (
                "changes_requested_then_rereview_then_queue",
                _pr(
                    9,
                    [_attempt("a", 0, 1), _attempt("b", 4, 5)],
                    reviews=[
                        ReviewVerdict(reviewer="ada", state="CHANGES_REQUESTED", submitted_at=_at(2)),
                        ReviewVerdict(reviewer="ada", state="COMMENTED", submitted_at=_at(3)),
                        ReviewVerdict(reviewer="ada", state="APPROVED", submitted_at=_at(6)),
                    ],
                    gates=[GateAttempt(attempt="gate-1", started_at=_at(7), completed_at=_at(8), failed=False)],
                ),
                [],
                [
                    (Kind.CI_RUNNING, 0, 1),
                    (Kind.WAITING_FOR_REVIEW, 1, 2),
                    (Kind.CHANGES_REQUESTED, 2, 4),
                    (Kind.CI_RUNNING, 4, 5),
                    (Kind.WAITING_FOR_REVIEW, 5, 6),
                    (Kind.APPROVED_NOT_ENQUEUED, 6, 7),
                    (Kind.MERGE_QUEUE, 7, 9),
                ],
            ),
            (
                "approval_from_another_reviewer_keeps_change_request_open",
                _pr(
                    4,
                    [_attempt("a", 0, 1)],
                    reviews=[
                        ReviewVerdict(reviewer="ada", state="CHANGES_REQUESTED", submitted_at=_at(2)),
                        ReviewVerdict(reviewer="bo", state="APPROVED", submitted_at=_at(3)),
                    ],
                ),
                [],
                [(Kind.CI_RUNNING, 0, 1), (Kind.WAITING_FOR_REVIEW, 1, 2), (Kind.CHANGES_REQUESTED, 2, 4)],
            ),
            (
                "open_pr_out_of_the_queue",
                _pr(
                    10,
                    [_attempt("a", 0, 1)],
                    reviews=[ReviewVerdict(reviewer="ada", state="APPROVED", submitted_at=_at(1))],
                    gates=[GateAttempt(attempt="gate-1", started_at=_at(2), completed_at=_at(3), failed=False)],
                    is_open=True,
                    trunk_out=True,
                ),
                [],
                [
                    (Kind.CI_RUNNING, 0, 1),
                    (Kind.APPROVED_NOT_ENQUEUED, 1, 2),
                    (Kind.MERGE_QUEUE, 2, 3),
                    (Kind.OUT_OF_MERGE_QUEUE, 3, 10),
                ],
            ),
            (
                "closed_pr_queue_stops_at_the_gate_end",
                _pr(
                    10,
                    [_attempt("a", 0, 1)],
                    reviews=[ReviewVerdict(reviewer="ada", state="APPROVED", submitted_at=_at(1))],
                    gates=[GateAttempt(attempt="gate-1", started_at=_at(2), completed_at=_at(3), failed=False)],
                    is_merged=False,
                ),
                [],
                [
                    (Kind.CI_RUNNING, 0, 1),
                    (Kind.APPROVED_NOT_ENQUEUED, 1, 2),
                    (Kind.MERGE_QUEUE, 2, 3),
                    (Kind.APPROVED_NOT_ENQUEUED, 3, 10),
                ],
            ),
            (
                "open_pr_still_red",
                _pr(5, [_attempt("a", 0, 1, failed=True)], reviews=[], is_open=True),
                [],
                [(Kind.CI_RUNNING, 0, 1), (Kind.RED_NOT_PROVABLE, 1, 5)],
            ),
            (
                "open_draft",
                _pr(10, [_attempt("a", 0, 1, failed=True)], is_open=True, is_draft=True),
                [],
                [(Kind.DRAFT, 0, 10)],
            ),
        ]
    )
    def test_segments(
        self,
        _name: str,
        pr: PRTimelineInput,
        master_failures: list[tuple[str, str, datetime]],
        expected: list[tuple[Kind, float, float]],
    ) -> None:
        segments = PRTimelineBuilder(pr, MasterFailureIndex(master_failures)).build()
        assert [(s.kind, s.started_at, s.ended_at) for s in segments] == [
            (kind, _at(start), _at(end)) for kind, start, end in expected
        ]


class TestDeliveryScope(SimpleTestCase):
    @parameterized.expand(
        [
            ("nothing", DeliveryScope, {}),
            ("two_people_at_once", DeliveryScope, {"author": "alice", "github_team": "team-replay"}),
            ("blank_author", DeliveryScope, {"author": "  "}),
            ("pr_without_repo", DeliveryScope, {"pr_number": 21}),
            ("summary_of_one_pull_request", SummaryScope, {"pr_number": 21, "repo": "PostHog/posthog"}),
        ]
    )
    def test_rejects_anything_but_one_scope(self, _name: str, scope_type: type[DeliveryScope], params: dict) -> None:
        with self.assertRaises(ValueError):
            scope_type.from_params(
                author=params.get("author"),
                github_team=params.get("github_team"),
                pr_number=params.get("pr_number"),
                repo=params.get("repo"),
            )

    def test_rejects_a_field_another_kind_owns(self) -> None:
        with self.assertRaises(ValueError):
            DeliveryScope(kind=DeliveryScopeKind.AUTHOR, github_team="team-replay")


def _facts(
    number: int, *, in_scope: bool, ready_hours: float, approved_after_hours: float | None, pushes_after: list[float]
) -> MergedPRFacts:
    merged_at = _at(100)
    ready_at = merged_at - timedelta(hours=ready_hours)
    return MergedPRFacts(
        number=number,
        author="alice" if in_scope else "bob",
        in_scope=in_scope,
        created_at=ready_at - timedelta(hours=1),
        merged_at=merged_at,
        ready_to_merge_seconds=int(ready_hours * 3600),
        approved_at=[ready_at + timedelta(hours=approved_after_hours)] if approved_after_hours is not None else [],
        pushed_at=[ready_at + timedelta(hours=h) for h in pushes_after],
        gate_attempts=[],
        cost=None,
    )


class TestComparisonTeamChoice(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_team", set(), {}, set(), [], Basis.NO_TEAM),
            ("one_team_needs_no_signal", {"team-a"}, {"team-b": 3}, set(), ["team-a"], Basis.ONLY_TEAM),
            (
                "a_group_that_owns_no_code_is_no_candidate",
                {"team-a", "approvers"},
                {},
                set(),
                ["team-a"],
                Basis.ONLY_TEAM,
            ),
            (
                "a_requested_team_owns_code_without_tests",
                {"team-a", "team-untested", "approvers"},
                {"team-untested": 2, "team-a": 1},
                set(),
                ["team-untested"],
                Basis.REVIEW_REQUESTS,
            ),
            (
                "the_pull_request_in_focus_wins",
                {"team-a", "team-b"},
                {"team-a": 5, "team-b": 1},
                {"team-b"},
                ["team-b"],
                Basis.PULL_REQUEST,
            ),
            (
                "every_team_the_focus_pull_request_asked_stays",
                {"team-a", "team-b", "team-c"},
                {"team-a": 5, "team-b": 1},
                {"team-a", "team-b"},
                ["team-a", "team-b"],
                Basis.PULL_REQUEST,
            ),
            (
                "the_most_requested_team_wins",
                {"team-a", "team-b"},
                {"team-a": 1, "team-b": 4},
                set(),
                ["team-b"],
                Basis.REVIEW_REQUESTS,
            ),
            (
                "a_tie_keeps_every_tied_team",
                {"team-a", "team-b", "team-c"},
                {"team-a": 2, "team-b": 2, "team-c": 1},
                set(),
                ["team-a", "team-b"],
                Basis.REVIEW_REQUESTS,
            ),
            (
                "requests_for_other_teams_show_every_code_team",
                {"team-b", "team-a", "approvers"},
                {"team-x": 3},
                set(),
                ["team-a", "team-b"],
                Basis.ALL_TEAMS,
            ),
        ]
    )
    def test_picks_the_teams_to_compare_with(
        self,
        _name: str,
        author_teams: set[str],
        requested_prs: dict[str, int],
        focus_requested: set[str],
        teams: list[str],
        basis: Basis,
    ) -> None:
        choice = choose_comparison_teams(
            author_teams=author_teams,
            code_teams={"team-a", "team-b", "team-c"},
            requested_prs=requested_prs,
            focus_requested=focus_requested,
        )

        assert (choice.teams, choice.basis) == (teams, basis)

    def test_every_team_is_a_candidate_without_any_evidence_of_owning_code(self) -> None:
        choice = choose_comparison_teams(
            author_teams={"team-untested", "approvers"}, code_teams={"team-a"}, requested_prs={}, focus_requested=set()
        )

        assert (choice.teams, choice.basis) == (["approvers", "team-untested"], Basis.ALL_TEAMS)


class TestScopeRepoFigure(SimpleTestCase):
    def test_scope_figures_read_only_the_prs_in_scope(self) -> None:
        facts = [
            _facts(1, in_scope=True, ready_hours=10, approved_after_hours=4, pushes_after=[0, 6]),
            # Approved while still a draft: nobody waited on a reviewer after it went ready.
            _facts(2, in_scope=False, ready_hours=2, approved_after_hours=-1, pushes_after=[1]),
            _facts(3, in_scope=False, ready_hours=30, approved_after_hours=None, pushes_after=[]),
        ]

        scope_facts = [fact for fact in facts if fact.in_scope]

        assert scope_repo_figure(scope_facts, facts, _median_ready_to_merge) == ScopeRepoFigure(scope=36000, repo=36000)
        assert scope_repo_figure(scope_facts, facts, _median_ready_to_first_approval) == ScopeRepoFigure(
            scope=14400, repo=7200
        )
        assert scope_repo_figure(scope_facts, facts, _before_approval_share) == ScopeRepoFigure(
            scope=0.4, repo=14400 / 43200
        )
        assert scope_repo_figure(scope_facts, facts, _pushes_after_approval) == ScopeRepoFigure(scope=1, repo=1)


def _review_row(review_id: int, pr_number: int, state: str, submitted_at: str) -> dict:
    return {
        "id": review_id,
        "pr_number": pr_number,
        "user": '{"login": "reviewer"}',
        "state": state,
        "commit_id": "",
        "submitted_at": submitted_at,
    }


def _member_row(member_id: int, login: str, team_slug: str) -> dict:
    return {"id": member_id, "login": login, "team_id": 1, "team_slug": team_slug, "team_name": team_slug}


_LISTED_KINDS = {
    21: [Kind.CI_RUNNING, Kind.RED_FIXED_BY_PUSH, Kind.CI_RUNNING, Kind.APPROVED_NOT_ENQUEUED, Kind.MERGE_QUEUE],
    23: [Kind.WAITING_FOR_REVIEW],
    24: [Kind.DRAFT],
    26: [Kind.WAITING_FOR_REVIEW],
}
_ALICE = SummaryScope.from_params(author="alice", github_team=None, pr_number=None, repo=None)
_ALICES_TEAM = SummaryScope.from_params(author=None, github_team="team-replay", pr_number=None, repo=None)


class TestDeliveryReadsOnWarehouse(_WarehouseMixin):
    def _seed(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(21, "alice", "closed", 0, _ago(3), merged_at=_ago(1)),
                _pr_row(22, "bob", "closed", 0, _ago(4), merged_at=_ago(1)),
                _pr_row(23, "alice", "open", 0, _ago(2)),
                _pr_row(24, "alice", "open", 1, _ago(1)),
                _pr_row(26, "alice", "open", 0, _ago(60)),
                # A bot's one-hour merge would drag the repo median down if bots counted.
                _pr_row(
                    25,
                    "dependabot[bot]",
                    "closed",
                    0,
                    _ago_offset_with_duration(2, 0, 0)[0],
                    merged_at=_ago_offset_with_duration(2, 3600, 0)[0],
                ),
            ],
        )
        self._create_table(
            "github_issue_events",
            ISSUE_EVENTS_COLUMNS,
            [
                # The outer events bound the observed range, so PR 22's never-drafted life sits inside it.
                _issue_event_row(1, "labeled", 22, _ago(10)),
                _issue_event_row(2, "ready_for_review", 21, _ago(2)),
                _issue_event_row(3, "labeled", 22, _ago(0)),
            ],
        )
        self._create_table(
            "github_reviews",
            REVIEWS_COLUMNS,
            [_review_row(1, 21, "APPROVED", _ago_offset_with_duration(2, 6 * 3600, 0)[0])],
        )
        self._create_table(
            "github_team_members",
            TEAM_MEMBERS_COLUMNS,
            [_member_row(1, "alice", "team-replay"), _member_row(2, "bob", "team-ingestion")],
        )
        red_start, red_end = _ago_offset_with_duration(2, 0, 3600)
        fix_start, fix_end = _ago_offset_with_duration(2, 8 * 3600, 3600)
        gate_start, gate_end = _ago_offset_with_duration(2, 20 * 3600, 3600)
        skipped_start, skipped_end = _ago_offset_with_duration(2, 12 * 3600, 60)
        post_merge_probe_start, post_merge_probe_end = _ago_offset_with_duration(1, 3600, 3600)
        old_gate_start, old_gate_end = _ago_offset_with_duration(20, 0, 3600)
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(3001, "CI", "sha21a", "completed", "failure", red_start, red_end, pr_number=21),
                _run_row(3002, "CI", "sha21b", "completed", "success", fix_start, fix_end, pr_number=21),
                # A skipped workflow still proves the authored commit reached CI, so it is a push.
                _run_row(3007, "CI", "sha21c", "completed", "skipped", skipped_start, skipped_end, pr_number=21),
                _run_row(
                    3003,
                    "CI",
                    "sha21queue",
                    "completed",
                    "success",
                    gate_start,
                    gate_end,
                    pr_number=9001,
                    head_branch="trunk-merge/pr-21/cabec75e-5181-4429-aea5-0501a52d0688",
                    actor="trunk-io[bot]",
                ),
                _run_row(3004, "CI", "sha22", "completed", "success", _ago(2), _ago(2), pr_number=22),
                _run_row(
                    3005,
                    "CI",
                    "sha21probe",
                    "completed",
                    "failure",
                    post_merge_probe_start,
                    post_merge_probe_end,
                    pr_number=9002,
                    head_branch="trunk-merge/pr-21/cabec75e-5181-4429-aea5-0501a52d0688-bisection",
                    actor="trunk-io[bot]",
                ),
                _run_row(
                    3006,
                    "CI",
                    "sha26queue",
                    "completed",
                    "failure",
                    old_gate_start,
                    old_gate_end,
                    pr_number=9003,
                    head_branch="trunk-merge/pr-26/old",
                    actor="trunk-io[bot]",
                ),
            ],
        )

    @parameterized.expand([("author", _ALICE), ("github_team", _ALICES_TEAM)])
    def test_summary_compares_scope_with_repo_and_flags_missing_sources(self, _name: str, scope: SummaryScope) -> None:
        self._seed()
        curated = CuratedGitHubSource.for_team(self.team)
        date_from = datetime.now(tz=UTC) - timedelta(days=7)

        summary = query_delivery_summary(curated=curated, scope=scope, date_from=date_from, date_to=None)

        assert (summary.opened_pr_count, summary.merged_pr_count, summary.open_pr_count, summary.draft_pr_count) == (
            3,
            1,
            2,
            1,
        )
        assert (summary.jobs_available, summary.review_data_available, summary.ready_data_available) == (
            False,
            True,
            True,
        )
        assert summary.median_ready_to_merge_seconds.scope == 86400
        assert summary.median_ready_to_merge_seconds.repo == (86400 + 3 * 86400) / 2
        assert summary.pushes_after_approval_per_merged_pr.scope == 2
        assert summary.merge_queue_attempts_per_merged_pr.scope == 1
        assert summary.failed_merge_queue_share.scope == 0
        overview = query_merge_queue_overview(
            curated=curated,
            date_from=date_from,
            date_to=None,
            prev_from=date_from - timedelta(days=7),
        )
        assert overview.avg_attempts_per_merge == summary.merge_queue_attempts_per_merged_pr.scope
        assert overview.failed_gate_merge_share == summary.failed_merge_queue_share.scope
        assert summary.push_count == 3
        assert summary.cost_per_merged_pr_usd.scope is None
        assert summary.lead_time.deploy_data_available is False

    @parameterized.expand(
        [
            ("author", _ALICE, {21, 23, 24, 26}),
            ("github_team", _ALICES_TEAM, {21, 23, 24, 26}),
            (
                "one_pull_request",
                DeliveryScope(
                    kind=DeliveryScopeKind.PULL_REQUEST, pr_number=21, repo_owner="PostHog", repo_name="posthog"
                ),
                {21},
            ),
        ]
    )
    def test_timelines_replay_each_pr_in_scope(self, _name: str, scope: DeliveryScope, expected: set[int]) -> None:
        self._seed()
        curated = CuratedGitHubSource.for_team(self.team)
        date_from = datetime.now(tz=UTC) - timedelta(days=7)

        timelines = query_pull_request_timelines(curated=curated, scope=scope, date_from=date_from, date_to=None)

        kinds = {item.number: [segment.kind for segment in item.segments] for item in timelines.items}
        assert kinds == {number: _LISTED_KINDS[number] for number in expected}
        merged = next(item for item in timelines.items if item.number == 21)
        assert timelines.merged_pr_count == 1
        assert [(entry.kind, entry.seconds_per_merged_pr) for entry in timelines.red_seconds_per_merged_pr] == [
            (Kind.RED_FIXED_BY_PUSH, 7 * 3600),
            (Kind.RED_PASSED_ON_RERUN, 0),
            (Kind.RED_MASTER_BROKEN, 0),
            (Kind.RED_NOT_PROVABLE, 0),
        ]
        assert merged.author.handle == "alice"
        assert [(push.head_sha, push.pushed_at) for push in merged.pushes] == [
            ("sha21a", _dt(_ago_offset_with_duration(2, 0, 3600)[0])),
            ("sha21b", _dt(_ago_offset_with_duration(2, 8 * 3600, 3600)[0])),
            ("sha21c", _dt(_ago_offset_with_duration(2, 12 * 3600, 60)[0])),
        ]
        assert merged.segments[-1].ended_at == merged.merged_at
        assert merged.started_at == _dt(_ago(2))
        starting_at_lookback = {item.number for item in timelines.items if item.started_at == date_from - CI_LOOKBACK}
        assert starting_at_lookback == expected & {26}

    def test_red_time_includes_merged_prs_beyond_the_list_limit(self) -> None:
        failure_start, failure_end = _ago_offset_with_duration(5, 0, 3600)
        fix_start, fix_end = _ago_offset_with_duration(4, 0, 3600)
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(1, "alice", "closed", 0, _ago(6), merged_at=_ago(1)),
                *[_pr_row(number, "alice", "closed", 0, _ago(3), merged_at=_ago(2)) for number in range(2, 202)],
                _pr_row(202, "alice", "open", 0, _ago(1)),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(4001, "CI", "sha-old", "completed", "failure", failure_start, failure_end, pr_number=1),
                _run_row(4002, "CI", "sha-fix", "completed", "success", fix_start, fix_end, pr_number=1),
            ],
        )
        curated = CuratedGitHubSource.for_team(self.team)
        original_source = curated.pr_source()
        source_reads = 0

        def source_after_close() -> str:
            nonlocal source_reads
            source_reads += 1
            if source_reads == 1:
                return original_source
            return f"(SELECT * FROM {original_source} WHERE number != 202)"

        with (
            patch.object(curated, "pr_source", side_effect=source_after_close),
            patch("products.engineering_analytics.backend.logic.queries._curated._QUERY_PAGE_SIZE", 1),
        ):
            timelines = query_pull_request_timelines(
                curated=curated,
                scope=_ALICE,
                date_from=datetime.now(tz=UTC) - timedelta(days=7),
                date_to=None,
            )

        red_by_kind = {entry.kind: entry.seconds_per_merged_pr for entry in timelines.red_seconds_per_merged_pr}
        expected = (_dt(fix_start) - _dt(failure_end)).total_seconds() / 201
        assert timelines.truncated is True
        assert len(timelines.items) == timelines.limit == 200
        assert all(item.number != 1 for item in timelines.items)
        assert timelines.merged_pr_count == 201
        assert red_by_kind[Kind.RED_FIXED_BY_PUSH] == expected

        with self.assertRaises(QueryWorkLimitExceededError):
            query_pull_request_timelines(
                curated=CuratedGitHubSource.for_team(self.team, query_limit=1),
                scope=_ALICE,
                date_from=datetime.now(tz=UTC) - timedelta(days=7),
                date_to=None,
            )

    def test_evidence_paging_keeps_the_next_row_when_an_earlier_row_leaves(self) -> None:
        failure_start, failure_end = _ago_offset_with_duration(3, 0, 3600)
        fix_start, fix_end = _ago_offset_with_duration(2, 0, 3600)
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(1, "alice", "closed", 0, _ago(4), merged_at=_ago(1))],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(4001, "CI", "sha-old", "completed", "failure", failure_start, failure_end, pr_number=1),
                _run_row(4002, "CI", "sha-fix", "completed", "success", fix_start, fix_end, pr_number=1),
            ],
        )
        curated = CuratedGitHubSource.for_team(self.team)
        original_run = curated.run
        evidence_page = 0

        def run_after_first_page(
            sql: str,
            *,
            query_type: str,
            placeholders: dict[str, ast.Expr] | None = None,
            workload: Workload = Workload.DEFAULT,
        ) -> HogQLQueryResponse | SimpleNamespace:
            nonlocal evidence_page
            if query_type == "engineering_analytics.pull_request_timelines_runs":
                evidence_page += 1
                if evidence_page == 2 and " OFFSET " in sql:
                    return SimpleNamespace(results=[])
            return original_run(sql, query_type=query_type, placeholders=placeholders, workload=workload)

        with (
            patch.object(curated, "run", side_effect=run_after_first_page),
            patch("products.engineering_analytics.backend.logic.queries._curated._QUERY_PAGE_SIZE", 1),
        ):
            timelines = query_pull_request_timelines(
                curated=curated,
                scope=_ALICE,
                date_from=datetime.now(tz=UTC) - timedelta(days=7),
                date_to=None,
            )

        assert [push.head_sha for push in timelines.items[0].pushes] == ["sha-old", "sha-fix"]

    def test_a_ready_event_after_the_close_still_builds_a_timeline(self) -> None:
        closed_at = _ago(2)
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(31, "alice", "closed", 0, _ago(4), closed_at=closed_at)],
        )
        self._create_table(
            "github_issue_events",
            ISSUE_EVENTS_COLUMNS,
            [_issue_event_row(1, "ready_for_review", 31, _ago(1))],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])
        curated = CuratedGitHubSource.for_team(self.team)
        scope = DeliveryScope(
            kind=DeliveryScopeKind.PULL_REQUEST, pr_number=31, repo_owner="PostHog", repo_name="posthog"
        )

        timelines = query_pull_request_timelines(
            curated=curated, scope=scope, date_from=datetime.now(tz=UTC) - timedelta(days=7), date_to=None
        )

        reopened = next(item for item in timelines.items if item.number == 31)
        assert reopened.started_at == _dt(_ago(4))
        assert reopened.segments != []

    @parameterized.expand([(1, Kind.CI_RUNNING), (2, Kind.RED_NOT_PROVABLE)])
    def test_only_a_first_attempt_queued_before_close_stays_in_the_timeline(
        self, attempt: int, expected_kind: Kind
    ) -> None:
        closed_at = _ago(2)
        queued_at = _ago_offset_with_duration(3, 86340, 0)[0]
        started_at, completed_at = _ago_offset_with_duration(2, 60, 60)
        run = _run_row(3101, "CI", "sha31", "completed", "success", started_at, completed_at, pr_number=31)
        run["created_at"] = queued_at
        run["run_attempt"] = attempt
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(31, "alice", "closed", 0, _ago(4), closed_at=closed_at)],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [run])
        failure_end = _ago_offset_with_duration(3, 86370, 0)[0]
        if attempt == 2:
            self._create_table(
                "github_workflow_jobs",
                WORKFLOW_JOBS_COLUMNS,
                [_job_row(31001, 3101, "Tests", "failure", started=queued_at, completed=failure_end)],
            )
        curated = CuratedGitHubSource.for_team(self.team)
        scope = DeliveryScope(
            kind=DeliveryScopeKind.PULL_REQUEST, pr_number=31, repo_owner="PostHog", repo_name="posthog"
        )

        timelines = query_pull_request_timelines(
            curated=curated, scope=scope, date_from=datetime.now(tz=UTC) - timedelta(days=7), date_to=None
        )

        closed = next(item for item in timelines.items if item.number == 31)
        assert closed.segments[-1].kind == expected_kind
        assert closed.segments[-1].started_at == _dt(queued_at if attempt == 1 else failure_end)
        assert closed.segments[-1].ended_at == _dt(closed_at)

    def test_an_earlier_ready_event_still_wins_when_the_latest_is_after_the_close(self) -> None:
        # PR 33 went ready, back to draft, then ready again; the events and pull-requests tables sync
        # apart, so its last ready event lands after its own row's close. Picking the unbounded latest
        # ready event and discarding it wholesale on an out-of-bounds read would lose the earlier,
        # still-valid one and overstate the review timeline from created_at instead.
        closed_at = _ago(2)
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(33, "alice", "closed", 0, _ago(6), closed_at=closed_at)],
        )
        self._create_table(
            "github_issue_events",
            ISSUE_EVENTS_COLUMNS,
            [
                _issue_event_row(1, "ready_for_review", 33, _ago(5)),
                _issue_event_row(2, "convert_to_draft", 33, _ago(4)),
                _issue_event_row(3, "ready_for_review", 33, _ago(1)),
            ],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])
        curated = CuratedGitHubSource.for_team(self.team)
        scope = DeliveryScope(
            kind=DeliveryScopeKind.PULL_REQUEST, pr_number=33, repo_owner="PostHog", repo_name="posthog"
        )

        timelines = query_pull_request_timelines(
            curated=curated, scope=scope, date_from=datetime.now(tz=UTC) - timedelta(days=7), date_to=None
        )

        reopened = next(item for item in timelines.items if item.number == 33)
        assert reopened.started_at == _dt(_ago(5))

    def test_a_never_ready_pr_starts_at_its_own_created_at(self) -> None:
        # PR 32 has an issue event, but never a ready_for_review one. The bounded ready-at read must
        # come back empty here, not fall back to ClickHouse's zero-value DateTime default, which would
        # read as truthy and pin the timeline to run_from instead.
        created_at = _ago(6)
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [_pr_row(32, "alice", "closed", 0, created_at, closed_at=_ago(5))],
        )
        self._create_table(
            "github_issue_events",
            ISSUE_EVENTS_COLUMNS,
            [_issue_event_row(1, "convert_to_draft", 32, _ago(5))],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])
        curated = CuratedGitHubSource.for_team(self.team)
        scope = DeliveryScope(
            kind=DeliveryScopeKind.PULL_REQUEST, pr_number=32, repo_owner="PostHog", repo_name="posthog"
        )

        timelines = query_pull_request_timelines(
            curated=curated, scope=scope, date_from=datetime.now(tz=UTC) - timedelta(days=7), date_to=None
        )

        never_ready = next(item for item in timelines.items if item.number == 32)
        assert never_ready.started_at == _dt(created_at)


_ISSUE_EVENTS_WITHOUT_TEAM_REQUESTS = {
    column: types for column, types in ISSUE_EVENTS_COLUMNS.items() if column != "requested_team"
}


def _team_request_row(event_id: int, pr_number: int, team_slug: str, created_at: str) -> dict:
    return {
        **_issue_event_row(event_id, "review_requested", pr_number, created_at, login="assigner[bot]"),
        "requested_team": f'{{"slug": "{team_slug}"}}',
    }


class TestDeliveryComparisonOnWarehouse(_WarehouseMixin):
    def _seed(self, *, with_team_requests: bool) -> None:
        # The census is keyed by repository, so the source has to name one.
        self._github_source = create_github_source(self.team, repository="PostHog/posthog")
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(21, "alice", "closed", 0, _ago(3), merged_at=_ago(1)),
                _pr_row(27, "alice", "closed", 0, _ago(3), merged_at=_ago(2)),
                _pr_row(23, "alice", "closed", 0, _ago(2), merged_at=_ago(1)),
                _pr_row(22, "bob", "closed", 0, _ago(4), merged_at=_ago(1)),
                _pr_row(28, "carol", "closed", 0, _ago(4), merged_at=_ago(2)),
                _pr_row(29, "dave", "closed", 0, _ago(4), merged_at=_ago(2)),
                # Opened before the issue events start, so their ready times are unknown.
                _pr_row(30, "erin", "closed", 0, _ago(12), merged_at=_ago(2)),
                _pr_row(31, "gina", "closed", 0, _ago(12), merged_at=_ago(2)),
                _pr_row(32, "hank", "closed", 0, _ago(12), merged_at=_ago(2)),
            ],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])
        # Alice is in two teams that own code and in an approver group that owns none. The two teams sit on
        # either side of MIN_OTHER_TEAM_AUTHORS: team-replay has exactly as many other authors with a ready
        # time as the floor asks for, team-ingestion one fewer, so its median stays hidden.
        self._create_table(
            "github_team_members",
            TEAM_MEMBERS_COLUMNS,
            [
                _member_row(1, "alice", "team-replay"),
                _member_row(2, "alice", "team-ingestion"),
                _member_row(3, "alice", "client-libraries-approvers"),
                _member_row(4, "bob", "team-replay"),
                _member_row(5, "carol", "team-ingestion"),
                _member_row(6, "dave", "team-replay"),
                _member_row(7, "erin", "team-replay"),
                _member_row(8, "gina", "team-ingestion"),
                _member_row(9, "hank", "team-ingestion"),
            ],
        )
        if with_team_requests:
            # Other authors' pull requests ask team-ingestion more often, and must not count for alice.
            self._create_table(
                "github_issue_events",
                ISSUE_EVENTS_COLUMNS,
                [
                    _issue_event_row(9, "labeled", 21, _ago(10)),
                    _team_request_row(1, 21, "team-replay", _ago(2)),
                    _team_request_row(2, 27, "team-replay", _ago(3)),
                    _team_request_row(3, 23, "team-ingestion", _ago(1)),
                    _team_request_row(4, 22, "team-ingestion", _ago(3)),
                    _team_request_row(5, 28, "team-ingestion", _ago(3)),
                ],
            )
        else:
            self._create_table(
                "github_issue_events",
                _ISSUE_EVENTS_WITHOUT_TEAM_REQUESTS,
                [_issue_event_row(1, "labeled", 21, _ago(10)), _issue_event_row(2, "labeled", 21, _ago(0))],
            )
        for owner_team in ("team-replay", "team-ingestion"):
            _create_event(
                event=CENSUS_EVENT,
                team=self.team,
                distinct_id="census",
                properties={"repository": "PostHog/posthog", "owner_team": owner_team, "test_file_count": 10},
                timestamp=datetime.now(tz=UTC) - timedelta(days=1),
            )
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("the_most_requested_team", True, None, Basis.REVIEW_REQUESTS, {"team-replay": 6}, (3, 9), None),
            ("the_team_the_focus_pr_asked", True, 23, Basis.PULL_REQUEST, {"team-ingestion": None}, (2, 8), 86400),
            (
                "every_code_team_without_requests",
                False,
                None,
                Basis.ALL_TEAMS,
                {"team-ingestion": None, "team-replay": 6},
                (3, 9),
                None,
            ),
        ]
    )
    def test_compares_the_author_with_their_team(
        self,
        _name: str,
        with_team_requests: bool,
        focus_pr: int | None,
        basis: Basis,
        team_merged_counts: dict[str, int | None],
        author_and_repo_counts: tuple[int, int],
        focus_ready_seconds: int | None,
    ) -> None:
        self._seed(with_team_requests=with_team_requests)
        curated = CuratedGitHubSource.for_team(self.team)

        comparison = query_delivery_comparison(
            curated=curated,
            author="alice",
            focus_pr=focus_pr,
            date_from=datetime.now(tz=UTC) - timedelta(days=7),
            date_to=None,
        )

        assert comparison.team_basis == basis
        assert {
            team.github_team: team.medians.merged_pr_count if team.medians else None for team in comparison.teams
        } == team_merged_counts
        assert (
            comparison.author_medians.merged_pr_count,
            comparison.repo_medians.merged_pr_count,
        ) == author_and_repo_counts
        focus = comparison.pull_request
        assert (focus.ready_to_merge_seconds if focus else None) == focus_ready_seconds


class TestDeliveryDeployWindow(_WarehouseMixin):
    def _seed(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(
                    30,
                    "alice",
                    "closed",
                    0,
                    "2026-01-07 08:00:00",
                    merged_at="2026-01-08 08:00:00",
                    merge_commit_sha="sha-before",
                    base_ref="main",
                    default_branch="main",
                ),
                _pr_row(
                    31,
                    "alice",
                    "closed",
                    0,
                    "2026-01-11 08:00:00",
                    merged_at="2026-01-12 08:00:00",
                    merge_commit_sha="sha-inside",
                    base_ref="main",
                    default_branch="main",
                ),
                _pr_row(
                    32,
                    "alice",
                    "closed",
                    0,
                    "2026-01-11 09:00:00",
                    merged_at="2026-01-12 09:00:00",
                    merge_commit_sha="sha-after",
                    base_ref="main",
                    default_branch="main",
                ),
            ],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])
        self._create_table(
            "github_deployments",
            DEPLOYMENTS_COLUMNS,
            [
                _deployment_row(3, "sha-before", "prod", "2026-01-11 09:30:00", production=True),
                _deployment_row(1, "sha-inside", "prod", "2026-01-12 09:30:00", production=True),
                _deployment_row(2, "sha-after", "prod", "2026-01-14 09:30:00", production=True),
            ],
        )
        self._create_table(
            "github_deployment_statuses",
            DEPLOYMENT_STATUSES_COLUMNS,
            [
                _status_row(31, 3, "success", "prod", "2026-01-11 10:00:00"),
                _status_row(11, 1, "success", "prod", "2026-01-12 10:00:00"),
                _status_row(21, 2, "success", "prod", "2026-01-14 10:00:00"),
            ],
        )

    def test_lead_time_population_matches_the_merged_count(self) -> None:
        self._seed()
        curated = CuratedGitHubSource.for_team(self.team)

        summary = query_delivery_summary(
            curated=curated,
            scope=_ALICE,
            date_from=_dt("2026-01-10T00:00:00"),
            date_to=_dt("2026-01-12T12:00:00"),
        )

        lead_time = summary.lead_time
        assert lead_time.deploy_data_available is True
        assert lead_time.merged_pr_count == 2
        # One deploy follows the report end and another belongs to an earlier merge, so neither
        # belongs in the count or its adjacent distribution.
        assert lead_time.deployed_merged_pr_count == 1
        assert lead_time.open_to_deploy.scope.pr_count == 1


class TestDeliveryEndpoints(APIBaseTest):
    def test_query_budget_exhaustion_does_not_return_partial_totals(self) -> None:
        with patch(
            "products.engineering_analytics.backend.presentation.views.delivery.api.get_pull_request_timelines",
            side_effect=QueryWorkLimitExceededError,
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/engineering_analytics/pull_request_timelines/?author=alice"
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "shorter date range" in response.json()["detail"]
        assert "merged_pr_count" not in response.json()

    @parameterized.expand(
        [
            ("delivery_summary", "", "exactly one of author, github_team"),
            ("pull_request_timelines", "", "exactly one of author, github_team"),
            ("delivery_comparison", "", "author is required"),
            ("delivery_comparison", "?author=alice&pr_number=21", "repo is required with pr_number"),
        ]
    )
    def test_rejects_a_missing_scope(self, action: str, query: str, message: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/{action}/{query}")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.json()["detail"]
