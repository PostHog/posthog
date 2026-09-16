from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.engineering_analytics.backend.facade.contracts import (
    DeliveryScopeKind,
    PRTimelineSegmentKind as Kind,
    ScopeRepoFigure,
)
from products.engineering_analytics.backend.logic.delivery_scope import DeliveryScope
from products.engineering_analytics.backend.logic.pr_timeline import (
    GateAttempt,
    MasterFailureIndex,
    PRTimelineBuilder,
    PRTimelineInput,
    ReviewVerdict,
    RunAttempt,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.delivery_summary import (
    CI_LOOKBACK,
    DeliverySummaryAggregator,
    MergedPRFacts,
    query_delivery_summary,
)
from products.engineering_analytics.backend.logic.queries.pull_request_timelines import query_pull_request_timelines
from products.engineering_analytics.backend.logic.views.source_schema import (
    DEPLOYMENT_STATUSES_COLUMNS,
    DEPLOYMENTS_COLUMNS,
    ISSUE_EVENTS_COLUMNS,
    PULL_REQUESTS_COLUMNS,
    REVIEWS_COLUMNS,
    TEAM_MEMBERS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _deployment_row,
    _issue_event_row,
    _pr_row,
    _run_row,
    _status_row,
)
from products.engineering_analytics.backend.tests._logic_helpers import (
    _ago,
    _ago_offset_with_duration,
    _dt,
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
    failed: bool = False,
    succeeded: bool | None = None,
    attempt: int = 1,
    jobs: tuple[str, ...] = (),
    pushed: float | None = None,
) -> RunAttempt:
    return RunAttempt(
        run_id=hash(sha) % 1000,
        workflow_name="CI",
        head_sha=sha,
        attempt=attempt,
        pushed_at=_at(start if pushed is None else pushed),
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
) -> PRTimelineInput:
    return PRTimelineInput(
        started_at=_at(0),
        ended_at=_at(end),
        is_open=is_open,
        is_merged=not is_open if is_merged is None else is_merged,
        is_draft=is_draft,
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
                    [_attempt("a", 1, 2, pushed=0)],
                    reviews=[ReviewVerdict(reviewer="ada", state="APPROVED", submitted_at=_at(0))],
                ),
                [],
                [(Kind.CI_RUNNING, 0, 2), (Kind.APPROVED_NOT_ENQUEUED, 2, 4)],
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
                    gates=[GateAttempt(started_at=_at(7), completed_at=_at(8))],
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
                    gates=[GateAttempt(started_at=_at(2), completed_at=_at(3))],
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
                    gates=[GateAttempt(started_at=_at(2), completed_at=_at(3))],
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
            ("nothing", {}),
            ("two_people_at_once", {"author": "alice", "github_team": "team-replay"}),
            ("blank_author", {"author": "  "}),
            ("pr_without_repo", {"pr_number": 21}),
        ]
    )
    def test_rejects_anything_but_one_scope(self, _name: str, params: dict) -> None:
        with self.assertRaises(ValueError):
            DeliveryScope.from_params(
                author=params.get("author"),
                github_team=params.get("github_team"),
                pr_number=params.get("pr_number"),
                repo=params.get("repo"),
            )


def _facts(
    number: int, *, in_scope: bool, ready_hours: float, approved_after_hours: float | None, pushes_after: list[float]
) -> MergedPRFacts:
    merged_at = _at(100)
    ready_at = merged_at - timedelta(hours=ready_hours)
    return MergedPRFacts(
        number=number,
        in_scope=in_scope,
        created_at=ready_at - timedelta(hours=1),
        merged_at=merged_at,
        ready_to_merge_seconds=int(ready_hours * 3600),
        approved_at=[ready_at + timedelta(hours=approved_after_hours)] if approved_after_hours is not None else [],
        pushed_at=[ready_at + timedelta(hours=h) for h in pushes_after],
        gate_attempts=[],
        cost=None,
    )


class TestDeliverySummaryAggregator(SimpleTestCase):
    def test_scope_figures_read_only_the_prs_in_scope(self) -> None:
        aggregator = DeliverySummaryAggregator(
            [
                _facts(1, in_scope=True, ready_hours=10, approved_after_hours=4, pushes_after=[0, 6]),
                # Approved while still a draft: nobody waited on a reviewer after it went ready.
                _facts(2, in_scope=False, ready_hours=2, approved_after_hours=-1, pushes_after=[1]),
                _facts(3, in_scope=False, ready_hours=30, approved_after_hours=None, pushes_after=[]),
            ]
        )

        assert aggregator.ready_to_merge(0.5) == ScopeRepoFigure(scope=36000, repo=36000)
        assert aggregator.median_ready_to_first_approval() == ScopeRepoFigure(scope=14400, repo=7200)
        assert aggregator.before_first_approval_share() == ScopeRepoFigure(scope=0.4, repo=14400 / 43200)
        assert aggregator.pushes_after_approval() == ScopeRepoFigure(scope=1, repo=1)


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


_ALICE = DeliveryScope.from_params(author="alice", github_team=None, pr_number=None, repo=None)
_ALICES_TEAM = DeliveryScope.from_params(author=None, github_team="team-replay", pr_number=None, repo=None)


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
        # Bob sits in another team, so the team scope must match alice's PRs only.
        self._create_table(
            "github_team_members",
            TEAM_MEMBERS_COLUMNS,
            [_member_row(1, "alice", "team-replay"), _member_row(2, "bob", "team-ingestion")],
        )
        red_start, red_end = _ago_offset_with_duration(2, 0, 3600)
        fix_start, fix_end = _ago_offset_with_duration(2, 8 * 3600, 3600)
        gate_start, gate_end = _ago_offset_with_duration(2, 20 * 3600, 3600)
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(3001, "CI", "sha21a", "completed", "failure", red_start, red_end, pr_number=21),
                _run_row(3002, "CI", "sha21b", "completed", "success", fix_start, fix_end, pr_number=21),
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
            ],
        )

    @parameterized.expand([("author", _ALICE), ("github_team", _ALICES_TEAM)])
    def test_summary_compares_scope_with_repo_and_flags_missing_sources(self, _name: str, scope: DeliveryScope) -> None:
        self._seed()
        curated = CuratedGitHubSource.for_team(self.team)

        summary = query_delivery_summary(
            curated=curated, scope=scope, date_from=datetime.now(tz=UTC) - timedelta(days=7), date_to=None
        )

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
        assert summary.pushes_after_approval_per_merged_pr.scope == 1
        assert summary.merge_queue_attempts_per_merged_pr.scope == 1
        assert summary.push_count == 2
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
        assert set(kinds) == expected
        assert kinds[21] == [
            Kind.CI_RUNNING,
            Kind.RED_FIXED_BY_PUSH,
            Kind.CI_RUNNING,
            Kind.APPROVED_NOT_ENQUEUED,
            Kind.MERGE_QUEUE,
        ]
        assert kinds.get(23, [Kind.WAITING_FOR_REVIEW]) == [Kind.WAITING_FOR_REVIEW]
        assert kinds.get(24, [Kind.DRAFT]) == [Kind.DRAFT]
        merged = next(item for item in timelines.items if item.number == 21)
        assert merged.author.handle == "alice"
        assert merged.pushes == 2
        assert merged.segments[-1].ended_at == merged.merged_at
        assert merged.started_at == _dt(_ago(2))
        old_open = next((item for item in timelines.items if item.number == 26), None)
        assert old_open is None or old_open.started_at == date_from - CI_LOOKBACK


class TestDeliveryDeployWindow(_WarehouseMixin):
    def _seed(self) -> None:
        # Two merges inside the window, each heading its own production deploy: one deploy lands
        # inside the reported window, the other two days after it.
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
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
                _deployment_row(1, "sha-inside", "prod", "2026-01-12 09:30:00", production=True),
                _deployment_row(2, "sha-after", "prod", "2026-01-14 09:30:00", production=True),
            ],
        )
        self._create_table(
            "github_deployment_statuses",
            DEPLOYMENT_STATUSES_COLUMNS,
            [
                _status_row(11, 1, "success", "prod", "2026-01-12 10:00:00"),
                _status_row(21, 2, "success", "prod", "2026-01-14 10:00:00"),
            ],
        )

    def test_deployed_count_stops_at_the_report_end(self) -> None:
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
        # The second PR's deploy is two days past the window end, so it is not deployed work yet,
        # and the count has to agree with the distribution beside it.
        assert lead_time.deployed_merged_pr_count == 1
        assert lead_time.open_to_deploy.scope.pr_count == 1


class TestDeliveryEndpoints(APIBaseTest):
    @parameterized.expand([("delivery_summary",), ("pull_request_timelines",)])
    def test_requires_exactly_one_scope(self, action: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/{action}/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "exactly one of author, github_team" in response.json()["detail"]
