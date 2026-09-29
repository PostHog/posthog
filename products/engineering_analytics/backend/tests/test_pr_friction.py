from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from products.engineering_analytics.backend.facade.contracts import (
    DeliveryScopeKind,
    PRTimelineSegmentKind as Kind,
)
from products.engineering_analytics.backend.logic.delivery_scope import DeliveryScope
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.pull_request_timelines import query_pull_request_timelines
from products.engineering_analytics.backend.logic.views import pr_friction
from products.engineering_analytics.backend.logic.views.source_schema import (
    ISSUE_EVENTS_COLUMNS,
    PULL_REQUESTS_COLUMNS,
    REVIEWS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _depot_attempt_row,
    _issue_event_row,
    _pr_row,
    _run_row,
)
from products.engineering_analytics.backend.tests._logic_helpers import (
    _ago,
    _ago_offset_with_duration,
    _job_row,
    _WarehouseMixin,
)

_DAY = 3
_GATE_ACTOR = "trunk-io[bot]"


def _span(offset_minutes: int, duration_minutes: int) -> tuple[str, str]:
    return _ago_offset_with_duration(_DAY, offset_minutes * 60, duration_minutes * 60)


def _at(offset_minutes: int) -> str:
    return _span(offset_minutes, 0)[0]


def _run(
    run_id: int,
    sha: str,
    conclusion: str | None,
    offset: int,
    duration: int,
    *,
    created_offset: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    start, end = _span(offset, duration)
    status = kwargs.pop("status", None) or ("completed" if conclusion else "in_progress")
    row = _run_row(run_id, kwargs.pop("name", "CI"), sha, status, conclusion, start, end, **kwargs)
    # The runs snapshot keeps the newest attempt's start, but the run was created with its first attempt.
    if created_offset is not None:
        row["created_at"] = _at(created_offset)
    return row


def _job(job_id: int, run_id: int, name: str, conclusion: str, offset: int, duration: int, **kwargs: Any) -> dict:
    start, end = _span(offset, duration)
    return _job_row(job_id, run_id, name, conclusion, started=start, completed=end, **kwargs)


def _gate(run_id: int, pr: int, attempt: str, conclusion: str | None, offset: int, duration: int) -> dict[str, Any]:
    return _run(
        run_id,
        f"queue{run_id}",
        conclusion,
        offset,
        duration,
        pr_number=9000 + run_id,
        head_branch=f"trunk-merge/pr-{pr}/{attempt}",
        actor=_GATE_ACTOR,
    )


def _merged(number: int, merged_offset: int, login: str = "alice") -> dict[str, Any]:
    return _pr_row(number, login, "closed", 0, _ago(_DAY + 1), merged_at=_at(merged_offset), default_branch="master")


class TestPRFrictionView(_WarehouseMixin):
    def _seed(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _merged(31, 360),
                _merged(32, 600),
                _merged(33, 180),
                _merged(34, 151),
                _merged(35, 60),
                _merged(36, 120),
                _merged(37, 360),
                _merged(38, 60, login="dependabot[bot]"),
                _merged(40, 190),
                _merged(41, 180),
                _merged(42, 200),
                _merged(43, 120),
                _merged(44, 120),
                _pr_row(39, "alice", "closed", 0, _ago(70), merged_at=_at(60), default_branch="master"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                # 31: a flaky failure that one re-run fixed.
                _run(3101, "sha31", "success", 30, 10, pr_number=31, run_attempt=2, created_offset=0),
                # 32: master is broken; two re-runs fail again, then a push lands after master recovers.
                _run(3201, "sha32", "failure", 40, 10, pr_number=32, run_attempt=3, created_offset=0),
                _run(3202, "sha32b", "success", 120, 10, pr_number=32),
                _run(3901, "master1", "failure", 0, 5, head_branch="master"),
                # 33: the author's own failure, fixed by the next push.
                _run(3301, "sha33a", "failure", 0, 15, pr_number=33),
                _run(3302, "sha33b", "success", 60, 20, pr_number=33),
                # 34: kicked out of the merge queue once, then merged on the second attempt.
                _run(3401, "sha34", "success", 0, 15, pr_number=34),
                _gate(3402, 34, "first", "failure", 60, 30),
                _gate(3403, 34, "second", "success", 120, 30),
                # 35: two runs of one workflow start in the same second. The unfinished one has the higher id and
                # stopped reporting days ago, so it ends at its start instead of running until the merge.
                _run(3501, "sha35", "success", 0, 5, pr_number=35, name="Lint"),
                _run(3502, "sha35", None, 0, 0, pr_number=35, name="Lint"),
                # 37: approved three hours after ready, then pushed again.
                _run(3701, "sha37a", "success", 0, 10, pr_number=37),
                _run(3702, "sha37b", "success", 300, 10, pr_number=37),
                _run(3801, "sha38", "success", 0, 10, pr_number=38),
                # 40: kicked out, pushed again and merged. A skipped gate run of the first attempt stayed
                # in_progress, which must not hold the queue open until the merge.
                _run(4001, "sha40a", "success", 0, 10, pr_number=40),
                _gate(4002, 40, "first", "failure", 20, 30),
                _gate(4003, 40, "first", None, 20, 0),
                _run(4004, "sha40b", "success", 120, 10, pr_number=40),
                _gate(4005, 40, "second", "success", 150, 30),
                # 41: "Re-run all" re-ran two failed workflows of one commit, and both failed again.
                _run(4101, "sha41a", "failure", 30, 10, pr_number=41, run_attempt=2, created_offset=0),
                _run(4102, "sha41a", "failure", 30, 10, pr_number=41, run_attempt=2, created_offset=0, name="Lint"),
                _run(4103, "sha41b", "success", 120, 10, pr_number=41),
                # 42: two failed workflows re-run separately, an hour apart, and both failed again.
                _run(4201, "sha42a", "failure", 90, 10, pr_number=42, run_attempt=2, created_offset=0),
                _run(4202, "sha42a", "failure", 30, 10, pr_number=42, run_attempt=2, created_offset=0, name="Lint"),
                _run(4203, "sha42b", "success", 150, 10, pr_number=42),
                # 43: stopped reporting with a stale conclusion, which must not turn the run red.
                _run(4301, "sha43", "failure", 0, 20, pr_number=43, status="in_progress"),
                # 44: a first attempt stopped reporting, but its job row settled as a failure before a fixing push.
                _run(4401, "sha44a", None, 0, 0, pr_number=44),
                _run(4402, "sha44b", "success", 60, 10, pr_number=44),
            ],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job(1, 3101, "test", "failure", 0, 10),
                _job(2, 3101, "test", "success", 30, 10, run_attempt=2),
                _job(3, 3201, "test (1/2)", "failure", 0, 10),
                _job(4, 3201, "test (1/2)", "failure", 20, 10, run_attempt=2),
                _job(5, 3201, "test (1/2)", "failure", 40, 10, run_attempt=3),
                _job(6, 3901, "test (2/2)", "failure", 0, 5, head_branch="master"),
                _job(7, 4101, "build", "failure", 0, 10),
                _job(8, 4101, "build", "failure", 30, 10, run_attempt=2),
                _job(9, 4102, "lint", "failure", 0, 10),
                _job(10, 4102, "lint", "failure", 30, 10, run_attempt=2),
                _job(11, 4201, "build", "failure", 0, 10),
                _job(12, 4201, "build", "failure", 90, 10, run_attempt=2),
                _job(13, 4202, "lint", "failure", 0, 10),
                _job(14, 4202, "lint", "failure", 30, 10, run_attempt=2),
                _job(15, 4401, "build", "failure", 0, 10),
            ],
        )
        self._create_table(
            "github_issue_events",
            ISSUE_EVENTS_COLUMNS,
            [
                _issue_event_row(1, "ready_for_review", 37, _at(60)),
                # 39 has events, just no ready event, so its ready time reads as NULL rather than missing.
                _issue_event_row(2, "review_requested", 39, _at(30)),
            ],
        )
        self._create_table(
            "github_reviews",
            REVIEWS_COLUMNS,
            [
                {
                    "id": 1,
                    "pr_number": 37,
                    "user": '{"login": "reviewer"}',
                    "state": "APPROVED",
                    "commit_id": "",
                    "submitted_at": _at(240),
                },
                # 39: opened before the event scan floor, so a missing ready event says nothing about drafts.
                {
                    "id": 2,
                    "pr_number": 39,
                    "user": '{"login": "reviewer"}',
                    "state": "APPROVED",
                    "commit_id": "",
                    "submitted_at": _at(30),
                },
            ],
        )

    def _view_rows(self) -> dict[int, dict[str, Any]]:
        query = pr_friction.build_team_view(self.team)
        assert query is not None
        response = execute_hogql_query(
            query=f"SELECT * FROM ({query})", team=self.team, query_type="engineering_analytics.test"
        )
        assert response.columns == list(pr_friction.FIELDS)
        return {row[2]: dict(zip(response.columns, row)) for row in response.results}

    def _seed_depot_ci(self) -> None:
        start, end = _span(0, 15)
        self._create_depot_table(
            [
                _depot_attempt_row(
                    ref="refs/pull/36/merge",
                    head_sha="sha36",
                    workflow_name="Backend CI on Depot",
                    workflow_status="failed",
                    workflow_created_at=start,
                    workflow_started_at=start,
                    workflow_finished_at=end,
                    job_key="ci-backend.yml:lint",
                    attempt_status="failed",
                    attempt_started_at=start,
                    attempt_finished_at=end,
                )
            ]
        )

    @parameterized.expand([("github_ci", False), ("depot_ci", True)])
    def test_view_matches_the_timeline_replay(self, _name: str, with_depot_ci: bool) -> None:
        if with_depot_ci:
            self._seed_depot_ci()
        self._seed()
        rows = self._view_rows()
        timelines = query_pull_request_timelines(
            curated=CuratedGitHubSource.for_team(self.team),
            scope=DeliveryScope(kind=DeliveryScopeKind.AUTHOR, author="alice"),
            date_from=datetime.now(tz=UTC) - pr_friction.FRICTION_WINDOW,
            date_to=None,
        )

        red_columns = {
            Kind.RED_PASSED_ON_RERUN: "flake_red_count",
            Kind.RED_MASTER_BROKEN: "master_red_count",
            Kind.RED_NOT_PROVABLE: "unknown_red_count",
            Kind.RED_FIXED_BY_PUSH: "own_red_count",
        }
        timeline_figures = {}
        for item in timelines.items:
            kinds = Counter(segment.kind for segment in item.segments)
            seconds: defaultdict[Kind, float] = defaultdict(float)
            for segment in item.segments:
                seconds[segment.kind] += (segment.ended_at - segment.started_at).total_seconds()
            timeline_figures[item.number] = {
                **{column: kinds[kind] for kind, column in red_columns.items()},
                "ci_running": seconds[Kind.CI_RUNNING],
                "merge_queue": seconds[Kind.MERGE_QUEUE],
            }
        view_figures = {
            number: {
                **{column: row[column] for column in red_columns.values()},
                "ci_running": sum(row["ci_wait_seconds"]),
                "merge_queue": row["queue_seconds"] or 0,
            }
            for number, row in rows.items()
            if number in timeline_figures
        }

        assert set(timeline_figures) == {31, 32, 33, 34, 35, 36, 37, 39, 40, 41, 42, 43, 44}
        assert view_figures == timeline_figures
        if with_depot_ci:
            assert view_figures[36]["ci_running"] > 0

    def test_view_counts_what_the_author_went_through(self) -> None:
        self._seed()
        rows = self._view_rows()

        picked = {
            number: {
                column: row[column]
                for column in (
                    "is_bot",
                    "push_count",
                    "flake_red_count",
                    "master_red_count",
                    "own_red_count",
                    "futile_rerun_count",
                    "first_approval_wait_seconds",
                    "pushes_after_approval",
                    "kickout_count",
                )
            }
            for number, row in rows.items()
        }
        base = {
            "is_bot": False,
            "push_count": 1,
            "flake_red_count": 0,
            "master_red_count": 0,
            "own_red_count": 0,
            "futile_rerun_count": 0,
            "first_approval_wait_seconds": None,
            "pushes_after_approval": None,
            "kickout_count": None,
        }
        assert picked == {
            31: {**base, "flake_red_count": 1},
            32: {**base, "push_count": 2, "master_red_count": 3, "futile_rerun_count": 2},
            33: {**base, "push_count": 2, "own_red_count": 1},
            34: {**base, "kickout_count": 1},
            35: base,
            36: {**base, "push_count": 0},
            37: {**base, "push_count": 2, "first_approval_wait_seconds": 3 * 3600.0, "pushes_after_approval": 1},
            38: {**base, "is_bot": True},
            39: {**base, "push_count": 0},
            40: {**base, "push_count": 2, "kickout_count": 1},
            41: {**base, "push_count": 2, "own_red_count": 2, "futile_rerun_count": 1},
            42: {**base, "push_count": 2, "own_red_count": 1, "futile_rerun_count": 2},
            43: base,
            44: {**base, "push_count": 2, "own_red_count": 1},
        }
        assert self._github_source is not None
        assert {row["source_id"] for row in rows.values()} == {str(self._github_source.id)}
        assert rows[35]["ci_wait_seconds"] == [0.0]
        # The first gate attempt ends when its finished runs end: 30 minutes, plus 40 from the second gate to the merge.
        assert rows[40]["queue_seconds"] == timedelta(minutes=70).total_seconds()
