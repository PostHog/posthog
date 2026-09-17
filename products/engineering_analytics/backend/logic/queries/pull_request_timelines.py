"""Curated query: pull requests in one scope as delivery timelines.

Selects the pull requests in scope (an author's or a GitHub team's open PRs plus the PRs merged in
the window, or one pull request whatever its state), fetches their immutable evidence, then replays
each PR's states with ``logic.pr_timeline``. Every read is scoped to the selected PR numbers, so the
scans track the listed work rather than the repository's history.

Run attempts come from the jobs table when it is synced: the runs snapshot keeps only a run's
newest attempt, so a failed first attempt that a re-run turned green is invisible without it.
Without jobs, each run contributes its newest attempt only and a flake reads as never red.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import (
    Author,
    DeliveryScopeKind,
    PRState,
    PRTimeline,
    PullRequestTimelines,
    RepoRef,
)
from products.engineering_analytics.backend.logic.delivery_scope import DeliveryScope
from products.engineering_analytics.backend.logic.merge_queue import gate_attempt_expr
from products.engineering_analytics.backend.logic.pr_timeline import (
    GateAttempt,
    MasterFailureIndex,
    PRTimelineBuilder,
    PRTimelineInput,
    ReviewVerdict,
    RunAttempt,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    DECISIVE_FAILURE_CONCLUSIONS,
    DECISIVE_FAILURE_CONCLUSIONS_SQL,
    UNPAGED_SCAN_LIMIT,
    run_started_floor_constant,
    run_windowed_job_created_floor_constant,
)
from products.engineering_analytics.backend.logic.queries.delivery_summary import CI_LOOKBACK
from products.engineering_analytics.backend.logic.queries.pr_cost import query_pr_costs_since
from products.engineering_analytics.backend.logic.views import issue_events

_LIMIT = 200

# Trunk states that mean the entry left the queue without landing.
_OUT_OF_QUEUE_STATES = frozenset({"failed", "cancelled"})

# A list scope shows what is still open plus what merged in the window; closed-unmerged work is not
# listed. A single pull request is shown whatever its state.
_LIST_WINDOW = "(pr.state = 'open' OR (pr.merged_at >= {date_from} __DATE_TO__))"

_PRS_SELECT = f"""
    SELECT
        pr.number, pr.title, pr.repo_owner, pr.repo_name, pr.state, pr.is_draft,
        pr.created_at, pr.merged_at, pr.closed_at, pr.default_branch,
        pr.author_handle, pr.author_avatar_url, pr.is_bot
    FROM __PR_SOURCE__ AS pr
    WHERE (__SCOPE__) AND __WINDOW__
    ORDER BY pr.created_at DESC
    LIMIT {_LIMIT + 1}
"""

_TRANSITIONS_SELECT = f"""
    SELECT pr_number, event, created_at
    FROM __EVENTS_SOURCE__ AS se
    WHERE pr_number IN {{pr_numbers}}
    ORDER BY created_at ASC, id ASC
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

_REVIEWS_SELECT = f"""
    SELECT pr_number, reviewer_login, state, submitted_at
    FROM __REVIEWS_SOURCE__ AS rv
    WHERE pr_number IN {{pr_numbers}}
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

# A skipped run never executes, so it adds no red or running time. Skipped and merge-queue runs are a
# third of a busy team's runs, so both stay out of this list to keep it under UNPAGED_SCAN_LIMIT.
_RUNS_SELECT = f"""
    SELECT
        id, pr_number, workflow_name, head_sha, status, conclusion, run_started_at, updated_at, run_attempt, created_at
    FROM __RUNS_SOURCE__ AS r
    WHERE pr_number IN {{pr_numbers}} AND run_started_at >= {{run_from}}
        AND NOT is_merge_queue AND ifNull(conclusion, '') != 'skipped'
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

# One row per merge-queue attempt: the queue runs several workflows for each attempt.
_GATE_ATTEMPTS_SELECT = f"""
    SELECT
        pr_number,
        min(run_started_at) AS started_at,
        max(updated_at) AS completed_at,
        countIf(status != 'completed' OR updated_at IS NULL) AS unfinished
    FROM __RUNS_SOURCE__ AS r
    WHERE pr_number IN {{pr_numbers}} AND run_started_at >= {{run_from}} AND is_merge_queue
    GROUP BY pr_number, __GATE_ATTEMPT__
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

# One row per run attempt. Re-run copies are GitHub's re-listing of jobs that never ran again, so
# they would stretch an attempt back to the previous attempt's start.
_JOB_ATTEMPTS_SELECT = f"""
    SELECT
        run_id,
        run_attempt,
        min(started_at) AS started_at,
        max(completed_at) AS completed_at,
        countIf(status != 'completed') AS unfinished,
        groupArrayIf(name, conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})) AS failed_jobs,
        countIf(conclusion NOT IN ('success', 'skipped')) AS unsuccessful
    FROM __JOBS_SOURCE__ AS j
    WHERE run_id IN {{run_ids}} AND NOT is_rerun_copy
    GROUP BY run_id, run_attempt
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

_MASTER_FAILURES_SELECT = f"""
    SELECT j.workflow_name, j.name, j.completed_at
    FROM __JOBS_SOURCE__ AS j
    INNER JOIN __RUNS_SOURCE__ AS r ON r.id = j.run_id
    WHERE r.head_branch = {{default_branch}}
        AND NOT r.is_merge_queue
        AND r.run_started_at >= {{run_from}}
        AND j.conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})
        AND j.completed_at IS NOT NULL
        AND j.workflow_name IN {{workflow_names}}
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

_TRUNK_STATE_SELECT = """
    SELECT pr_number, argMax(state, state_changed_at) AS state
    FROM __TRUNK_SOURCE__ AS tq
    WHERE pr_number IN {pr_numbers}
    GROUP BY pr_number
"""


@frozen
class _JobAttempt:
    """One attempt of a run, rolled up from its jobs."""

    attempt: int
    started_at: datetime
    # None while any job of the attempt is still running.
    completed_at: datetime | None
    failed_jobs: tuple[str, ...]
    # Every job finished with success or skipped.
    succeeded: bool


class PullRequestTimelinesQuery:
    """Collects the evidence for the pull requests in one scope and replays each into a timeline."""

    def __init__(
        self, curated: CuratedGitHubSource, *, scope: DeliveryScope, date_from: datetime, date_to: datetime | None
    ) -> None:
        self._curated = curated
        self._scope = scope
        self._date_from = date_from
        self._date_to = date_to
        self._now = datetime.now(tz=UTC)

    def _result(self, items: list[PRTimeline], *, truncated: bool) -> PullRequestTimelines:
        return PullRequestTimelines(
            scope_kind=self._scope.kind,
            scope=self._scope.label,
            has_membership_data=self._curated.members_source() is not None,
            review_data_available=self._curated.reviews_source() is not None,
            jobs_available=self._curated.jobs_source() is not None,
            merge_queue_state_available=self._curated.trunk_merge_queue_source() is not None,
            generated_at=self._now,
            items=items,
            truncated=truncated,
            limit=_LIMIT,
        )

    def run(self) -> PullRequestTimelines:
        prs = self._query_prs()
        truncated = len(prs) > _LIMIT
        prs = prs[:_LIMIT]
        if not prs:
            return self._result([], truncated=False)

        pr_numbers = sorted({int(row[0]) for row in prs})
        # A day of slack below the oldest listed PR keeps its first CI run inside the scan.
        run_from = min(row[6] for row in prs) - timedelta(days=1)
        if self._scope.kind != DeliveryScopeKind.PULL_REQUEST:
            # An open PR is listed whatever its age, and one old PR would stretch every scan back months.
            # A listed PR's CI is read from the same lookback the summary uses, and its timeline starts there.
            run_from = max(run_from, self._date_from - CI_LOOKBACK)
        ready_at = self._query_ready_at(pr_numbers, run_from)
        reviews = self._query_reviews(pr_numbers)
        attempts, gates = self._query_attempts(pr_numbers, run_from)
        default_branch = next((row[9] for row in prs if row[9]), "")
        master_failures = self._query_master_failures(attempts, default_branch, run_from)
        out_of_queue = self._query_out_of_queue(pr_numbers)
        # Floored like the runs scan: an unfloored cost read scans the whole jobs history for a team scope.
        costs = query_pr_costs_since(curated=self._curated, pr_numbers=pr_numbers, run_from=run_from)

        items = []
        for row in prs:
            (
                number,
                title,
                repo_owner,
                repo_name,
                state,
                is_draft,
                created_at,
                merged_at,
                closed_at,
                _branch,
                author_handle,
                author_avatar_url,
                is_bot,
            ) = row
            number = int(number)
            is_open = state == PRState.OPEN
            ended_at = merged_at or (closed_at if not is_open else None) or self._now
            started_at = max(
                created_at
                if is_open and is_draft
                else self._started_at(ready_at.get(number, []), created_at, ended_at),
                run_from,
            )
            pr_attempts = [attempt for attempt in attempts.get(number, []) if attempt.started_at <= ended_at]
            builder = PRTimelineBuilder(
                PRTimelineInput(
                    started_at=started_at,
                    ended_at=ended_at,
                    is_open=is_open,
                    is_merged=merged_at is not None,
                    is_draft=bool(is_draft) and is_open,
                    attempts=pr_attempts,
                    gate_attempts=[gate for gate in gates.get(number, []) if gate.started_at <= ended_at],
                    reviews=reviews.get(number, []) if reviews is not None else None,
                    trunk_out_of_queue=number in out_of_queue,
                ),
                master_failures,
            )
            cost = costs.get(number)
            items.append(
                PRTimeline(
                    number=number,
                    title=title or "",
                    author=Author(
                        handle=author_handle or "",
                        display_name=author_handle or "",
                        avatar_url=author_avatar_url or "",
                        is_bot=bool(is_bot),
                    ),
                    repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
                    state=PRState(state),
                    is_draft=bool(is_draft),
                    created_at=created_at,
                    started_at=started_at,
                    merged_at=merged_at,
                    pushes=builder.pushes(),
                    estimated_cost_usd=cost.estimated_cost_usd if cost else None,
                    billable_minutes=cost.billable_seconds / 60 if cost else None,
                    segments=builder.build(),
                )
            )
        return self._result(items, truncated=truncated)

    @staticmethod
    def _started_at(ready_events: list[datetime], created_at: datetime, ended_at: datetime) -> datetime:
        """The last ready_for_review before the end, else created_at (never drafted, or unsynced)."""
        before_end = [at for at in ready_events if created_at <= at <= ended_at]
        return max(before_end) if before_end else created_at

    def _query_prs(self) -> list[tuple]:
        placeholders: dict[str, ast.Expr] = {
            "date_from": ast.Constant(value=self._date_from),
            **self._scope.placeholders(),
        }
        date_to_clause = ""
        if self._date_to is not None:
            placeholders["date_to"] = ast.Constant(value=self._date_to)
            date_to_clause = "AND pr.merged_at <= {date_to}"
        window = "1 = 1" if self._scope.kind == DeliveryScopeKind.PULL_REQUEST else _LIST_WINDOW
        sql = (
            _PRS_SELECT.replace("__SCOPE__", self._scope.pr_predicate(members_source=self._curated.members_source()))
            .replace("__WINDOW__", window)
            .replace("__PR_SOURCE__", self._curated.pr_source())
            .replace("__DATE_TO__", date_to_clause)
        )
        response = self._curated.run(
            sql, query_type="engineering_analytics.pull_request_timelines_prs", placeholders=placeholders
        )
        return [row for row in response.results or [] if row[6] is not None]

    def _query_ready_at(self, pr_numbers: list[int], run_from: datetime) -> dict[int, list[datetime]]:
        # A timeline never starts before run_from, so an older ready event cannot move its start. The
        # floor keeps the scan from parsing the whole append-growing events history.
        source = self._curated.issue_events_source(created_floor=True)
        if source is None:
            return {}
        response = self._curated.run(
            _TRANSITIONS_SELECT.replace("__EVENTS_SOURCE__", source),
            query_type="engineering_analytics.pull_request_timelines_transitions",
            placeholders={
                "pr_numbers": ast.Constant(value=pr_numbers),
                "event_created_floor": run_started_floor_constant(run_from),
            },
        )
        ready_at: dict[int, list[datetime]] = defaultdict(list)
        for number, event, created_at in response.results or []:
            if event == issue_events.READY_FOR_REVIEW_EVENT:
                ready_at[int(number)].append(created_at)
        return ready_at

    def _query_reviews(self, pr_numbers: list[int]) -> dict[int, list[ReviewVerdict]] | None:
        """Reviews per PR, or None when the reviews table is not synced."""
        source = self._curated.reviews_source()
        if source is None:
            return None
        response = self._curated.run(
            _REVIEWS_SELECT.replace("__REVIEWS_SOURCE__", source),
            query_type="engineering_analytics.pull_request_timelines_reviews",
            placeholders={"pr_numbers": ast.Constant(value=pr_numbers)},
        )
        reviews: dict[int, list[ReviewVerdict]] = defaultdict(list)
        for number, reviewer, state, submitted_at in response.results or []:
            reviews[int(number)].append(ReviewVerdict(reviewer=reviewer or "", state=state, submitted_at=submitted_at))
        return reviews

    def _query_attempts(
        self, pr_numbers: list[int], run_from: datetime
    ) -> tuple[dict[int, list[RunAttempt]], dict[int, list[GateAttempt]]]:
        runs_source = self._curated.run_source(started_floor=True)
        placeholders: dict[str, ast.Expr] = {
            "pr_numbers": ast.Constant(value=pr_numbers),
            "run_from": ast.Constant(value=run_from),
            "run_started_floor": run_started_floor_constant(run_from),
        }
        response = self._curated.run(
            _RUNS_SELECT.replace("__RUNS_SOURCE__", runs_source),
            query_type="engineering_analytics.pull_request_timelines_runs",
            placeholders=placeholders,
        )
        runs = [row for row in response.results or [] if row[6] is not None]
        # A run on its first attempt that did not fail has exactly one attempt, and its run row already
        # describes it. Only re-runs (earlier attempts) and failures (failed job names) need the jobs.
        job_attempts = self._query_job_attempts(
            [int(row[0]) for row in runs if int(row[8] or 1) > 1 or row[5] in DECISIVE_FAILURE_CONCLUSIONS],
            run_from,
        )

        attempts: dict[int, list[RunAttempt]] = defaultdict(list)
        for (
            run_id,
            number,
            workflow_name,
            head_sha,
            status,
            conclusion,
            started_at,
            updated_at,
            attempt,
            created,
        ) in runs:
            run_attempts = job_attempts.get(int(run_id), [])
            pushed_at = created or started_at
            completed = status == "completed"
            run_failed = completed and conclusion in DECISIVE_FAILURE_CONCLUSIONS
            newest_attempt = int(attempt or 1)
            for job_attempt in run_attempts:
                # The run row decides its newest attempt's outcome and end: the jobs sync can still hold a
                # queued job row, miss the failing job's row, or hold only the jobs that finished first,
                # after the run itself completed.
                is_newest = job_attempt.attempt == newest_attempt
                failed = bool(job_attempt.failed_jobs) or (is_newest and run_failed)
                completed_at = job_attempt.completed_at
                succeeded = job_attempt.succeeded and not failed
                if is_newest and completed:
                    completed_at = updated_at or completed_at
                    succeeded = conclusion == "success" and not failed
                attempts[int(number)].append(
                    RunAttempt(
                        run_id=int(run_id),
                        workflow_name=workflow_name or "",
                        head_sha=head_sha or "",
                        attempt=job_attempt.attempt,
                        pushed_at=pushed_at,
                        started_at=job_attempt.started_at,
                        completed_at=completed_at,
                        failed=failed,
                        succeeded=succeeded,
                        failed_jobs=job_attempt.failed_jobs,
                    )
                )
            # The jobs sync can lag behind the run row, so the run's newest attempt comes from the run
            # row whenever the jobs have not reported it yet.
            if run_attempts and newest_attempt <= max(job_attempt.attempt for job_attempt in run_attempts):
                continue
            attempts[int(number)].append(
                RunAttempt(
                    run_id=int(run_id),
                    workflow_name=workflow_name or "",
                    head_sha=head_sha or "",
                    attempt=newest_attempt,
                    pushed_at=pushed_at,
                    started_at=started_at,
                    completed_at=updated_at if completed else None,
                    failed=run_failed,
                    succeeded=completed and conclusion == "success",
                    failed_jobs=(),
                )
            )

        gates_response = self._curated.run(
            _GATE_ATTEMPTS_SELECT.replace("__RUNS_SOURCE__", runs_source).replace(
                "__GATE_ATTEMPT__", gate_attempt_expr("r.head_branch")
            ),
            query_type="engineering_analytics.pull_request_timelines_gate_attempts",
            placeholders=placeholders,
        )
        gates: dict[int, list[GateAttempt]] = defaultdict(list)
        for number, started_at, completed_at, unfinished in gates_response.results or []:
            if started_at is not None:
                gates[int(number)].append(
                    GateAttempt(started_at=started_at, completed_at=None if unfinished else completed_at)
                )
        return attempts, gates

    def _query_job_attempts(self, run_ids: list[int], run_from: datetime) -> dict[int, list[_JobAttempt]]:
        source = self._curated.jobs_source(created_floor=True)
        if source is None or not run_ids:
            return {}
        response = self._curated.run(
            _JOB_ATTEMPTS_SELECT.replace("__JOBS_SOURCE__", source),
            query_type="engineering_analytics.pull_request_timelines_job_attempts",
            placeholders={
                "run_ids": ast.Constant(value=run_ids),
                "job_created_floor": run_windowed_job_created_floor_constant(run_from),
            },
        )
        by_run: dict[int, list[_JobAttempt]] = defaultdict(list)
        for run_id, run_attempt, started_at, completed_at, unfinished, failed_jobs, unsuccessful in (
            response.results or []
        ):
            if started_at is None:
                continue
            by_run[int(run_id)].append(
                _JobAttempt(
                    attempt=int(run_attempt or 1),
                    started_at=started_at,
                    completed_at=None if unfinished else completed_at,
                    failed_jobs=tuple(failed_jobs or ()),
                    succeeded=not unfinished and not unsuccessful,
                )
            )
        return by_run

    def _query_master_failures(
        self, attempts: dict[int, list[RunAttempt]], default_branch: str, run_from: datetime
    ) -> MasterFailureIndex:
        # Filtered by workflow, not by job name: the index compares job names without their shard
        # suffix, and an exact-name filter would drop the other shards of the same job.
        workflow_names = sorted(
            {
                attempt.workflow_name
                for pr_attempts in attempts.values()
                for attempt in pr_attempts
                if attempt.failed_jobs
            }
        )
        jobs_source = self._curated.jobs_source(created_floor=True)
        if not workflow_names or not default_branch or jobs_source is None:
            return MasterFailureIndex([])
        response = self._curated.run(
            _MASTER_FAILURES_SELECT.replace("__JOBS_SOURCE__", jobs_source).replace(
                "__RUNS_SOURCE__", self._curated.run_source(started_floor=True)
            ),
            query_type="engineering_analytics.pull_request_timelines_master_failures",
            placeholders={
                "default_branch": ast.Constant(value=default_branch),
                "workflow_names": ast.Constant(value=workflow_names),
                "run_from": ast.Constant(value=run_from),
                "run_started_floor": run_started_floor_constant(run_from),
                "job_created_floor": run_windowed_job_created_floor_constant(run_from),
            },
        )
        return MasterFailureIndex(
            [(workflow or "", name or "", completed_at) for workflow, name, completed_at in response.results or []]
        )

    def _query_out_of_queue(self, pr_numbers: list[int]) -> set[int]:
        source = self._curated.trunk_merge_queue_source()
        if source is None:
            return set()
        response = self._curated.run(
            _TRUNK_STATE_SELECT.replace("__TRUNK_SOURCE__", source),
            query_type="engineering_analytics.pull_request_timelines_trunk_state",
            placeholders={"pr_numbers": ast.Constant(value=pr_numbers)},
        )
        return {int(number) for number, state in response.results or [] if state in _OUT_OF_QUEUE_STATES}


def query_pull_request_timelines(
    *, curated: CuratedGitHubSource, scope: DeliveryScope, date_from: datetime, date_to: datetime | None
) -> PullRequestTimelines:
    return PullRequestTimelinesQuery(curated, scope=scope, date_from=date_from, date_to=date_to).run()
