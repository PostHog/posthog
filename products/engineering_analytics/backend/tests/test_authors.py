from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from products.engineering_analytics.backend.facade.contracts import (
    AuthorRepoFigure,
    PRTimelineSegmentKind as Kind,
)
from products.engineering_analytics.backend.logic.pr_timeline import (
    GateAttempt,
    MasterFailureIndex,
    PRTimelineBuilder,
    PRTimelineInput,
    ReviewVerdict,
    RunAttempt,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.author_summary import (
    AuthorSummaryAggregator,
    MergedPRFacts,
    query_author_summary,
)
from products.engineering_analytics.backend.logic.queries.author_timelines import query_author_timelines
from products.engineering_analytics.backend.logic.views.source_schema import (
    ISSUE_EVENTS_COLUMNS,
    PULL_REQUESTS_COLUMNS,
    REVIEWS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import _issue_event_row, _pr_row, _run_row
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
    sha: str, start: float, end: float | None, *, failed: bool = False, attempt: int = 1, jobs: tuple[str, ...] = ()
) -> RunAttempt:
    return RunAttempt(
        run_id=hash(sha) % 1000,
        workflow_name="CI",
        head_sha=sha,
        attempt=attempt,
        started_at=_at(start),
        completed_at=_at(end) if end is not None else None,
        failed=failed,
        failed_jobs=jobs,
    )


def _pr(
    end: float,
    attempts: list[RunAttempt],
    *,
    reviews: list[ReviewVerdict] | None = None,
    gates: list[GateAttempt] | None = None,
    is_open: bool = False,
    is_draft: bool = False,
    trunk_out: bool = False,
) -> PRTimelineInput:
    return PRTimelineInput(
        started_at=_at(0),
        ended_at=_at(end),
        is_open=is_open,
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
                    reviews=[ReviewVerdict(state="APPROVED", submitted_at=_at(5))],
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
                        ReviewVerdict(state="CHANGES_REQUESTED", submitted_at=_at(2)),
                        ReviewVerdict(state="COMMENTED", submitted_at=_at(3)),
                        ReviewVerdict(state="APPROVED", submitted_at=_at(6)),
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
                "open_pr_out_of_the_queue",
                _pr(
                    10,
                    [_attempt("a", 0, 1)],
                    reviews=[ReviewVerdict(state="APPROVED", submitted_at=_at(1))],
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


def _facts(
    number: int, *, is_author: bool, ready_hours: float, approved_after_hours: float | None, pushes_after: list[float]
) -> MergedPRFacts:
    merged_at = _at(100)
    ready_at = merged_at - timedelta(hours=ready_hours)
    return MergedPRFacts(
        number=number,
        is_author=is_author,
        created_at=ready_at - timedelta(hours=1),
        merged_at=merged_at,
        ready_to_merge_seconds=int(ready_hours * 3600),
        approved_at=[ready_at + timedelta(hours=approved_after_hours)] if approved_after_hours is not None else [],
        pushed_at=[ready_at + timedelta(hours=h) for h in pushes_after],
        gate_attempts=[],
        cost=None,
    )


class TestAuthorSummaryAggregator(SimpleTestCase):
    def test_author_figures_read_only_the_authors_prs(self) -> None:
        aggregator = AuthorSummaryAggregator(
            [
                _facts(1, is_author=True, ready_hours=10, approved_after_hours=4, pushes_after=[0, 6]),
                # Approved while still a draft: nobody waited on a reviewer after it went ready.
                _facts(2, is_author=False, ready_hours=2, approved_after_hours=-1, pushes_after=[1]),
                _facts(3, is_author=False, ready_hours=30, approved_after_hours=None, pushes_after=[]),
            ]
        )

        assert aggregator.ready_to_merge(0.5) == AuthorRepoFigure(author=36000, repo=36000)
        assert aggregator.median_ready_to_first_approval() == AuthorRepoFigure(author=14400, repo=7200)
        assert aggregator.before_first_approval_share() == AuthorRepoFigure(author=0.4, repo=14400 / 43200)
        assert aggregator.pushes_after_approval() == AuthorRepoFigure(author=1, repo=1)


def _review_row(review_id: int, pr_number: int, state: str, submitted_at: str) -> dict:
    return {
        "id": review_id,
        "pr_number": pr_number,
        "user": '{"login": "reviewer"}',
        "state": state,
        "commit_id": "",
        "submitted_at": submitted_at,
    }


class TestAuthorReadsOnWarehouse(_WarehouseMixin):
    def _seed(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(21, "alice", "closed", 0, _ago(3), merged_at=_ago(1)),
                _pr_row(22, "bob", "closed", 0, _ago(4), merged_at=_ago(1)),
                _pr_row(23, "alice", "open", 0, _ago(2)),
                _pr_row(24, "alice", "open", 1, _ago(1)),
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

    def test_summary_compares_author_with_repo_and_flags_missing_sources(self) -> None:
        self._seed()
        curated = CuratedGitHubSource.for_team(self.team)

        summary = query_author_summary(
            curated=curated, author="alice", date_from=datetime.now(tz=UTC) - timedelta(days=7), date_to=None
        )

        assert (summary.opened_pr_count, summary.merged_pr_count, summary.open_pr_count, summary.draft_pr_count) == (
            3,
            1,
            1,
            1,
        )
        assert (summary.jobs_available, summary.review_data_available, summary.ready_data_available) == (
            False,
            True,
            True,
        )
        assert summary.median_ready_to_merge_seconds.author == 86400
        assert summary.median_ready_to_merge_seconds.repo == (86400 + 3 * 86400) / 2
        assert summary.pushes_after_approval_per_merged_pr.author == 1
        assert summary.merge_queue_attempts_per_merged_pr.author == 1
        assert summary.push_count == 2
        assert summary.cost_per_merged_pr_usd.author is None
        assert summary.lead_time.deploy_data_available is False

    def test_timelines_replay_each_pr(self) -> None:
        self._seed()
        curated = CuratedGitHubSource.for_team(self.team)

        timelines = query_author_timelines(
            curated=curated, author="alice", date_from=datetime.now(tz=UTC) - timedelta(days=7), date_to=None
        )

        kinds = {item.number: [segment.kind for segment in item.segments] for item in timelines.items}
        assert kinds == {
            21: [
                Kind.CI_RUNNING,
                Kind.RED_FIXED_BY_PUSH,
                Kind.CI_RUNNING,
                Kind.APPROVED_NOT_ENQUEUED,
                Kind.MERGE_QUEUE,
            ],
            23: [Kind.WAITING_FOR_REVIEW],
            24: [Kind.DRAFT],
        }
        merged = next(item for item in timelines.items if item.number == 21)
        assert merged.pushes == 2
        assert merged.segments[-1].ended_at == merged.merged_at
        assert merged.started_at == _dt(_ago(2))


class TestAuthorEndpoints(APIBaseTest):
    @parameterized.expand([("author_summary",), ("author_pull_request_timelines",)])
    def test_requires_author(self, action: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/{action}/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "author is required"
