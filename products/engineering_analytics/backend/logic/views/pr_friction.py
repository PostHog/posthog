"""Curated per-PR friction view: what each recently merged pull request put its author through.

One row per pull request merged in the last ``FRICTION_WINDOW``. The red and running time comes from
the same replay as ``logic/pr_timeline.py``, written as set-based HogQL so one query covers every PR in
the window. The rules are the timeline's own:

- A commit's check state per workflow is its latest started attempt, ordered by (start, attempt, run id).
- A failed latest attempt is red from its completion until the next attempt of that workflow starts, the
  next push arrives, or the pull request merges.
- A red stretch is labelled by what turned it green: every failed workflow passed a later attempt on the
  same commit (a re-run), else every failed job also failed on the default branch within
  ``MASTER_FAILURE_PROXIMITY`` (master broken), else a later push exists (fixed by a push), else not provable.
- Precedence at any moment: merge queue, red, CI running, then review states.

``tests/test_pr_friction.py`` replays seeded pull requests through both this view and
``PullRequestTimelinesQuery`` and asserts they agree, so the two definitions cannot drift apart.

The view counts friction, it does not score it. Curves and weights are applied when it is read
(``logic/friction.py``), so a weight change needs no rematerialization. Red stretches are counted, not
timed: an author who leaves a red pull request alone is hardly affected, so the length of a stretch
says little about what the author went through.

Materialized on the managed-view schedule. Each run replaces the table, so it only ever holds the
pull requests inside the window.
"""

import re
from datetime import timedelta
from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatArrayDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
)

from products.engineering_analytics.backend.logic.delivery_scope import CI_LOOKBACK
from products.engineering_analytics.backend.logic.merge_queue import GATE_RUN_LOOKBACK, gate_attempt_expr
from products.engineering_analytics.backend.logic.pr_timeline import MASTER_FAILURE_PROXIMITY
from products.engineering_analytics.backend.logic.queries._workflow_filters import DECISIVE_FAILURE_CONCLUSIONS_SQL
from products.engineering_analytics.backend.logic.sources import resolve_job_source_tables
from products.engineering_analytics.backend.logic.views import (
    issue_events,
    pull_requests,
    reviews,
    workflow_jobs,
    workflow_runs,
)

if TYPE_CHECKING:
    from posthog.models.team import Team

VIEW_NAME = "engineering_analytics_pr_friction"

FRICTION_WINDOW = timedelta(days=30)

FIELDS: dict[str, FieldOrTable] = {
    "repo_owner": StringDatabaseField(name="repo_owner"),
    "repo_name": StringDatabaseField(name="repo_name"),
    "number": IntegerDatabaseField(name="number"),
    "author": StringDatabaseField(name="author"),
    "author_avatar_url": StringDatabaseField(name="author_avatar_url"),
    "is_bot": BooleanDatabaseField(name="is_bot"),
    "merged_at": DateTimeDatabaseField(name="merged_at"),
    "push_count": IntegerDatabaseField(name="push_count"),
    # Red stretches by what turned them green. Adjacent pieces of one kind are one stretch.
    "flake_red_count": IntegerDatabaseField(name="flake_red_count"),
    "master_red_count": IntegerDatabaseField(name="master_red_count"),
    "unknown_red_count": IntegerDatabaseField(name="unknown_red_count"),
    "own_red_count": IntegerDatabaseField(name="own_red_count"),
    "futile_rerun_count": IntegerDatabaseField(name="futile_rerun_count"),
    "ci_wait_seconds": FloatArrayDatabaseField(name="ci_wait_seconds"),
    # NULL when the reviews table is not synced, nobody approved, or the ready time is not observed.
    "first_approval_wait_seconds": FloatDatabaseField(name="first_approval_wait_seconds", nullable=True),
    "pushes_after_approval": IntegerDatabaseField(name="pushes_after_approval", nullable=True),
    # NULL when the pull request never entered the merge queue.
    "queue_seconds": FloatDatabaseField(name="queue_seconds", nullable=True),
    "kickout_count": IntegerDatabaseField(name="kickout_count", nullable=True),
    # A read filters on its own authorized source: the view unions every source, and a member can be denied some.
    "source_id": StringDatabaseField(name="source_id"),
}

# The same regex as ``queries/master_failures.strip_shard_suffix``, so shards of one job group together.
_STRIP_SHARD = "replaceRegexpOne({name}, '\\\\s*\\\\((\\\\d+)/(\\\\d+)\\\\)(\\\\))?$', '\\\\3')"
_SOURCE_ID = re.compile(r"[0-9a-fA-F-]{1,64}")
_FAR = "toDateTime64('2100-01-01 00:00:00', 6, 'UTC')"
_EPOCH = "toDateTime64('1970-01-01 00:00:00', 6, 'UTC')"


def _days(delta: timedelta) -> int:
    return delta.days


def _raw_floor(days: int) -> str:
    # Date-only string one day below the window, compared against the raw ISO strings the source lands.
    return f"toString(toDate(now() - INTERVAL {days + 1} DAY))"


def _strip_shard(expr: str) -> str:
    return _STRIP_SHARD.format(name=expr)


def build_query(
    *,
    source_id: str,
    pull_requests_table: str,
    workflow_runs_table: str,
    workflow_jobs_table: str,
    issue_events_table: str | None,
    reviews_table: str | None,
) -> str:
    if not _SOURCE_ID.fullmatch(source_id):
        raise ValueError(f"not a source id: {source_id!r}")
    window_days = _days(FRICTION_WINDOW)
    run_days = window_days + _days(CI_LOOKBACK)
    gate_days = window_days + _days(GATE_RUN_LOOKBACK)
    # Re-runs create their jobs before the run's newest start, so the jobs floor sits a week lower.
    job_floor_days = run_days + 7
    proximity_hours = int(MASTER_FAILURE_PROXIMITY.total_seconds() // 3600)

    prs = f"({pull_requests.build_query(pull_requests_table)})"
    runs = workflow_runs.build_query(
        workflow_runs_table, pull_requests_table=pull_requests_table, started_floor=True
    ).replace("{run_started_floor}", _raw_floor(run_days))
    jobs = workflow_jobs.build_query(workflow_jobs_table, created_floor=True).replace(
        "{job_created_floor}", _raw_floor(job_floor_days)
    )
    run_from = f"now() - INTERVAL {run_days} DAY"

    if issue_events_table:
        events = issue_events.build_query(issue_events_table, created_floor=True).replace(
            "{event_created_floor}", _raw_floor(run_days)
        )
        ready_join = f"""
        LEFT JOIN (
            SELECT e.pr_number AS number,
                maxOrNullIf(e.created_at, e.event = '{issue_events.READY_FOR_REVIEW_EVENT}' AND e.created_at <= p2.merged_at) AS ready_at
            FROM ({events}) AS e
            INNER JOIN pr AS p2 ON p2.number = e.pr_number
            GROUP BY e.pr_number
        ) AS rd ON rd.number = p.number"""
        ready_expr = "if(rd.ready_at > toDateTime('2000-01-01 00:00:00') AND rd.ready_at <= p.merged_at, rd.ready_at, p.created_at)"
        # Without a ready event, the created time stands in only when the event scan covers the whole life
        # of the PR. An older PR may have left draft before the scan floor, and an approval given while it
        # was a draft would then read as the first approval.
        # A PR without a ready event has a NULL ready_at, and NULL must not pass the guard as "not false".
        ready_observed_expr = (
            f"ifNull(rd.ready_at > toDateTime('2000-01-01 00:00:00') AND rd.ready_at <= p.merged_at, false) "
            f"OR p.created_at >= now() - INTERVAL {run_days} DAY"
        )
    else:
        ready_join = ""
        ready_expr = "p.created_at"
        ready_observed_expr = "false"

    if reviews_table:
        approvals_join = f"""
        LEFT JOIN (
            SELECT rv.pr_number AS number, groupArray(rv.submitted_at) AS approved_at
            FROM ({reviews.build_query(reviews_table)}) AS rv
            WHERE rv.state = '{reviews.APPROVED_STATE}' AND rv.pr_number IN (SELECT number FROM pr)
            GROUP BY rv.pr_number
        ) AS ap ON ap.number = p.number"""
        approvals_expr = "ap.approved_at"
    else:
        approvals_join = ""
        approvals_expr = "[]"

    return f"""
WITH
pr AS (
    SELECT number, author_handle AS author, author_avatar_url, is_bot, repo_owner, repo_name, default_branch,
        created_at, merged_at
    FROM {prs} AS p
    WHERE merged_at >= now() - INTERVAL {window_days} DAY AND merged_at <= now()
),
bounds AS (
    SELECT p.number AS number, p.author AS author, p.author_avatar_url AS author_avatar_url, p.is_bot AS is_bot,
        p.repo_owner AS repo_owner,
        p.repo_name AS repo_name, p.merged_at AS ended_at,
        {ready_expr} AS ready_at,
        {ready_observed_expr} AS ready_observed,
        greatest({ready_expr}, {run_from}) AS started_at,
        {approvals_expr} AS approved_at
    FROM pr AS p{ready_join}{approvals_join}
),
job_attempts AS (
    SELECT run_id, groupArray(tuple(attempt_number, started_at, completed_at, unfinished, failed_jobs, unsuccessful)) AS jas
    FROM (
        SELECT run_id, ifNull(run_attempt, 1) AS attempt_number,
            min(started_at) AS started_at,
            max(completed_at) AS completed_at,
            countIf(status != 'completed') AS unfinished,
            groupArrayIf(name, conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})) AS failed_jobs,
            countIf(conclusion NOT IN ('success', 'skipped')) AS unsuccessful
        FROM ({jobs}) AS j
        WHERE NOT is_rerun_copy
        GROUP BY run_id, attempt_number
        HAVING started_at IS NOT NULL
    )
    GROUP BY run_id
),
master AS (
    SELECT workflow_name, groupArray(tuple(job, completed_at)) AS fails
    FROM (
        SELECT ifNull(workflow_name, '') AS workflow_name,
            {_strip_shard("name")} AS job,
            parseDateTimeBestEffort(completed_at) AS completed_at
        FROM {workflow_jobs_table}
        WHERE created_at >= {_raw_floor(run_days)}
            AND head_branch IN (SELECT default_branch FROM pr WHERE default_branch != '')
            -- The timeline counts failures of default-branch runs that started in its window, gate runs excluded.
            AND run_id IN (SELECT id FROM ({runs}) AS mr WHERE NOT mr.is_merge_queue AND mr.run_started_at >= {run_from})
            AND conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})
            AND completed_at IS NOT NULL
    )
    WHERE completed_at IS NOT NULL
    GROUP BY workflow_name
),
run_rows AS (
    -- One row per run, with its attempts assembled the way PullRequestTimelinesQuery does.
    SELECT r.pr_number AS number, r.id AS run_id, r.is_merge_queue AS is_merge_queue, r.head_sha AS head_sha,
        r.head_branch AS head_branch, r.workflow_name AS workflow_name, r.status AS status,
        r.run_started_at AS run_started_at, r.updated_at AS updated_at,
        coalesce(r.created_at, r.run_started_at) AS queued_at,
        b.started_at AS s0, b.ended_at AS e0,
        NOT r.is_merge_queue AND ifNull(r.conclusion, '') != 'skipped' AS is_ci_run,
        ifNull(r.run_attempt, 1) AS newest,
        r.status = 'completed' AS run_completed,
        r.status = 'completed' AND ifNull(r.conclusion, '') IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL}) AS run_failed,
        r.status = 'completed' AND ifNull(r.conclusion, '') = 'success' AS run_success,
        -- Only re-runs and failures need job rows: a first attempt that did not fail is its run row.
        if(ifNull(r.run_attempt, 1) > 1 OR ifNull(r.conclusion, '') IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL}), ja.jas, []) AS jas,
        m.fails AS master_fails
    FROM ({runs}) AS r
    INNER JOIN bounds AS b ON b.number = r.pr_number
    LEFT JOIN job_attempts AS ja ON ja.run_id = r.id
    LEFT JOIN master AS m ON m.workflow_name = r.workflow_name
    WHERE r.run_started_at >= {run_from} AND r.pr_number > 0
),
runs_with_attempts AS (
    -- Attempt tuple: (attempt, queued_at, started_at, completed_at, failed, succeeded, failed_jobs, run_id).
    -- The run row decides its newest attempt's outcome and end; the jobs sync can lag behind it.
    SELECT *,
        arrayConcat(
            arrayMap(ja -> tuple(
                ja.1,
                queued_at,
                ja.2,
                if(ja.1 = newest AND run_completed, coalesce(updated_at, if(ja.4 > 0, NULL, ja.3)), if(ja.4 > 0, NULL, ja.3)),
                length(ja.5) > 0 OR (ja.1 = newest AND run_failed),
                if(ja.1 = newest AND run_completed, run_success AND length(ja.5) = 0, ja.4 = 0 AND ja.6 = 0 AND length(ja.5) = 0),
                ja.5,
                run_id
            ), jas),
            if(length(jas) = 0 OR newest > arrayMax(arrayMap(ja -> ja.1, jas)),
                [tuple(newest, queued_at, run_started_at, if(run_completed, updated_at, NULL), run_failed, run_success, arrayFilter(x -> 0, ['']), run_id)],
                [])
        ) AS attempts_raw
    FROM run_rows
),
runs_explained AS (
    -- Attempt tuple gains element 9: every failed job also failed on the default branch nearby.
    SELECT number, is_merge_queue, head_sha, head_branch, workflow_name, status, run_started_at, updated_at, queued_at,
        s0, e0, is_ci_run, run_failed,
        if(is_ci_run, arrayMap(a -> tuple(a.1, a.2, a.3, a.4, a.5, a.6, a.7, a.8,
                a.5 AND a.4 IS NOT NULL AND length(a.7) > 0 AND arrayAll(fj -> arrayExists(
                    mf -> mf.1 = {_strip_shard("fj")}
                        AND mf.2 >= a.4 - toIntervalHour({proximity_hours}) AND mf.2 <= a.4 + toIntervalHour({proximity_hours}),
                    ifNull(master_fails, [])), a.7)),
            arrayFilter(a -> a.3 <= e0 OR (a.1 = 1 AND a.2 <= e0), attempts_raw)), []) AS attempts
    FROM runs_with_attempts
),
workflows AS (
    -- One group per workflow on one commit, or per merge-queue gate attempt.
    SELECT number, is_merge_queue, key, wf_key,
        any(s0) AS w_s0, any(e0) AS w_e0,
        minIf(queued_at, NOT is_merge_queue) AS first_created,
        arraySort(x -> tuple(x.3, x.1, x.8), arrayFlatten(groupArray(attempts))) AS xs,
        minIf(run_started_at, is_merge_queue AND run_started_at >= now() - INTERVAL {gate_days} DAY AND run_started_at <= e0) AS gate_start,
        if(countIf(is_merge_queue AND run_started_at >= now() - INTERVAL {gate_days} DAY AND run_started_at <= e0
                AND (status != 'completed' OR updated_at IS NULL)) > 0,
            {_FAR}, maxIf(updated_at, is_merge_queue AND run_started_at >= now() - INTERVAL {gate_days} DAY AND run_started_at <= e0)) AS gate_end,
        countIf(is_merge_queue AND run_started_at >= now() - INTERVAL {gate_days} DAY AND run_started_at <= e0) > 0 AS has_gate,
        max(is_merge_queue AND run_started_at >= now() - INTERVAL {gate_days} DAY AND run_started_at <= e0 AND run_failed) AS gate_failed
    FROM (
        SELECT *,
            if(is_merge_queue, {gate_attempt_expr("head_branch")}, head_sha) AS key,
            if(is_merge_queue, '', workflow_name) AS wf_key
        FROM runs_explained
    )
    GROUP BY number, is_merge_queue, key, wf_key
),
workflow_spans AS (
    -- Red: a failed latest attempt, from its end until the next attempt starts.
    -- Running: a started latest attempt that has not finished, or a first attempt still waiting to start.
    SELECT number, is_merge_queue, key, w_s0 AS s0, w_e0 AS e0, first_created, gate_start, gate_end, has_gate, gate_failed,
        arrayFilter(t -> t.2 > t.1, arrayMap(i -> tuple(
                assumeNotNull(xs[i].4),
                if(i < length(xs), xs[i + 1].3, {_FAR}),
                arrayExists(y -> y.3 >= xs[i].4 AND y.4 IS NOT NULL AND y.6, xs),
                xs[i].9),
            arrayFilter(i -> xs[i].5 AND xs[i].4 IS NOT NULL, arrayEnumerate(xs)))) AS reds,
        arrayFilter(t -> t.2 > t.1, arrayConcat(
            arrayMap(i -> tuple(xs[i].3, least(coalesce(xs[i].4, {_FAR}), if(i < length(xs), xs[i + 1].3, {_FAR}))), arrayEnumerate(xs)),
            if(length(xs) > 0, [tuple(arrayMin(arrayMap(y -> if(y.1 = 1, y.2, {_FAR}), xs)), xs[1].3)], [])
        )) AS runs,
        arrayCount(x -> x.1 > 1 AND x.5, xs) AS futile_reruns
    FROM workflows
),
commits AS (
    SELECT number, is_merge_queue, key,
        any(s0) AS c_s0, any(e0) AS c_e0,
        min(first_created) AS pushed_at,
        arrayFlatten(groupArray(reds)) AS reds, arrayFlatten(groupArray(runs)) AS runs,
        sum(futile_reruns) AS futile_reruns,
        any(gate_start) AS gate_start, any(gate_end) AS gate_end, max(has_gate) AS has_gate, max(gate_failed) AS gate_failed
    FROM workflow_spans
    GROUP BY number, is_merge_queue, key
),
per_pr AS (
    SELECT number, any(c_s0) AS p_s0, any(c_e0) AS p_e0,
        arraySort(p -> tuple(p.1, p.4), groupArrayIf(tuple(pushed_at, reds, runs, key), NOT is_merge_queue AND pushed_at <= c_e0)) AS pushes,
        groupArrayIf(tuple(gate_start, gate_end), is_merge_queue AND has_gate) AS gates,
        countIf(is_merge_queue AND has_gate AND gate_failed) AS kickouts,
        sumIf(futile_reruns, NOT is_merge_queue AND pushed_at <= c_e0) AS futile_reruns
    FROM commits
    GROUP BY number
),
clipped AS (
    -- Each commit's spans only count while it is the head: from its push until the next push.
    SELECT number, p_s0 AS s0, p_e0 AS e0, gates, kickouts, futile_reruns, pushes,
        arrayFlatten(arrayMap(k -> arrayMap(t -> tuple(
                greatest(t.1, pushes[k].1), least(t.2, if(k < length(pushes), pushes[k + 1].1, {_FAR})), t.3, t.4, k < length(pushes)),
            pushes[k].2), arrayEnumerate(pushes))) AS reds,
        arrayFlatten(arrayMap(k -> arrayMap(t -> tuple(
                greatest(t.1, pushes[k].1), least(t.2, if(k < length(pushes), pushes[k + 1].1, {_FAR}))),
            pushes[k].3), arrayEnumerate(pushes))) AS runs,
        if(length(pushes) > 0, pushes[length(pushes)].1, {_EPOCH}) AS last_push_at
    FROM per_pr
    WHERE p_e0 > p_s0
),
with_queue AS (
    -- The queue span runs from the first gate attempt after the last push to the merge.
    SELECT number, s0, e0, reds, runs, kickouts, futile_reruns, pushes, length(gates) > 0 AS queued,
        arrayConcat(gates, if(arrayExists(g -> g.1 >= last_push_at, gates),
            [tuple(arrayMin(arrayMap(g -> g.1, arrayFilter(g -> g.1 >= last_push_at, gates))), e0)], [])) AS queue_spans
    FROM clipped
),
points AS (
    SELECT number, reds, runs, queue_spans, kickouts, futile_reruns, pushes, queued,
        arraySort(arrayDistinct(arrayConcat([s0, e0], arrayFilter(p -> p > s0 AND p < e0, arrayConcat(
            arrayMap(t -> t.1, reds), arrayMap(t -> t.2, reds),
            arrayMap(t -> t.1, runs), arrayMap(t -> t.2, runs),
            arrayMap(t -> t.1, queue_spans), arrayMap(t -> t.2, queue_spans),
            arrayMap(p -> p.1, pushes)
        ))))) AS pts
    FROM with_queue
),
pieces AS (
    -- Piece tuple: (kind, seconds, index of the head push).
    SELECT number, kickouts, futile_reruns, queued, length(pushes) AS push_count, arrayMap(p -> p.1, pushes) AS pushes_at,
        arrayMap(k -> tuple(
            multiIf(
                arrayExists(q -> q.1 <= pts[k] AND pts[k] < q.2, queue_spans), 'merge_queue',
                NOT arrayExists(t -> t.1 <= pts[k] AND pts[k] < t.2, reds),
                    if(arrayExists(t -> t.1 <= pts[k] AND pts[k] < t.2, runs), 'ci_running', 'other'),
                arrayAll(t -> t.3, arrayFilter(t -> t.1 <= pts[k] AND pts[k] < t.2, reds)), 'red_passed_on_rerun',
                arrayAll(t -> t.4, arrayFilter(t -> t.1 <= pts[k] AND pts[k] < t.2, reds)), 'red_master_broken',
                arrayFilter(t -> t.1 <= pts[k] AND pts[k] < t.2, reds)[1].5, 'red_fixed_by_push',
                'red_not_provable'),
            ifNull(dateDiff('second', pts[k], pts[k + 1]), 0),
            arrayCount(p -> p.1 <= pts[k], pushes)),
        range(1, length(pts))) AS parts
    FROM points
),
counted AS (
    SELECT number, kickouts, futile_reruns, queued, push_count, pushes_at,
        arrayMap(kind -> arrayCount(i -> parts[i].1 = kind AND (i = 1 OR parts[i - 1].1 != kind), arrayEnumerate(parts)),
            ['red_passed_on_rerun', 'red_master_broken', 'red_not_provable', 'red_fixed_by_push']) AS red_counts,
        arrayMap(n -> 1.0 * arraySum(arrayMap(p -> if(p.1 = 'ci_running' AND p.3 = n, p.2, 0), parts)), range(1, push_count + 1)) AS ci_wait,
        toFloat(arraySum(arrayMap(p -> if(p.1 = 'merge_queue', p.2, 0), parts))) AS queue_seconds
    FROM pieces
)
SELECT
    b.repo_owner AS repo_owner,
    b.repo_name AS repo_name,
    b.number AS number,
    b.author AS author,
    b.author_avatar_url AS author_avatar_url,
    b.is_bot AS is_bot,
    b.ended_at AS merged_at,
    ifNull(c.push_count, 0) AS push_count,
    ifNull(c.red_counts[1], 0) AS flake_red_count,
    ifNull(c.red_counts[2], 0) AS master_red_count,
    ifNull(c.red_counts[3], 0) AS unknown_red_count,
    ifNull(c.red_counts[4], 0) AS own_red_count,
    ifNull(c.futile_reruns, 0) AS futile_rerun_count,
    ifNull(c.ci_wait, []) AS ci_wait_seconds,
    if(first_approval_at IS NULL, NULL, toFloat(greatest(dateDiff('second', b.ready_at, first_approval_at), 0))) AS first_approval_wait_seconds,
    if(first_approval_at IS NULL, NULL, arrayCount(t -> t > first_approval_at AND t <= b.ended_at, ifNull(c.pushes_at, []))) AS pushes_after_approval,
    if(ifNull(c.queued, 0), c.queue_seconds, NULL) AS queue_seconds,
    if(ifNull(c.queued, 0), c.kickouts, NULL) AS kickout_count,
    '{source_id}' AS source_id
FROM (
    SELECT *,
        -- The first approval after ready; an approval given while still a draft counts as approved at ready.
        if(NOT ready_observed, NULL,
            if(arrayExists(t -> t >= ready_at AND t <= ended_at, ifNull(approved_at, [])),
                arrayMin(arrayFilter(t -> t >= ready_at AND t <= ended_at, ifNull(approved_at, []))),
                if(arrayExists(t -> t < ready_at, ifNull(approved_at, [])), ready_at, NULL))) AS first_approval_at
    FROM bounds
) AS b
LEFT JOIN counted AS c ON c.number = b.number
"""


def build_team_view(team: "Team") -> str | None:
    """The view body for a team: one SELECT per repository with runs, jobs and pull requests synced."""
    sources = [source for source in resolve_job_source_tables(team) if source.pull_requests]
    if not sources:
        return None
    # Each SELECT carries its own WITH, so each sits in its own subquery to keep the CTE names apart.
    return "\nUNION ALL\n".join(
        f"SELECT * FROM ({build_query(source_id=source.source_id, pull_requests_table=source.pull_requests, workflow_runs_table=source.runs_source, workflow_jobs_table=source.jobs_source, issue_events_table=source.issue_events, reviews_table=source.reviews)})"
        for source in sources
        if source.pull_requests
    )
