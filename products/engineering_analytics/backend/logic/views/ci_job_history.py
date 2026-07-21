"""Per-job-attempt CI history with commit attribution — the green/red boundary substrate.

Composes the curated ``workflow_jobs`` and ``workflow_runs`` builders (one row per job attempt,
jobs LEFT JOIN runs) exactly like ``job_costs``, but instead of the cost model it exposes commit
attribution: who authored the head commit, its message, and which PR the run belongs to. That is
what lets a caller answer "master went red at SHA X, authored by Y, via PR Z" — the boundary
analysis the CI-breakage investigation skill runs.

``build_query`` renders the SELECT for one GitHub source; ``build_team_view`` unions every
qualifying source. The jobs↔runs join is a LEFT JOIN on ``run_id`` alone: the runs warehouse
snapshot upserts by ``id`` and keeps only the newest attempt's row per run, so requiring
``run_attempt`` equality would blank attribution for every earlier-attempt job after a re-run.
Attribution is attempt-invariant (a re-run is the same commit), so joining on ``run_id`` is
correct; ``run_attempt`` in the output comes from the jobs side. A LEFT JOIN so a job attempt is
never dropped when its run row is missing. ClickHouse fills the unmatched run side with type
defaults (empty repo/sha, ``pr_number`` 0), not NULL — HogQL doesn't set ``join_use_nulls`` — so a
missing run reads as empty attribution rather than a real repo.

Commit attribution comes from the run's ``head_commit`` Nullable-JSON column, which the shared
``workflow_runs`` builder deliberately does not surface (other embedders — cost, health, PR list —
don't need it, and the builder stays lean). Rather than widen the shared builder, this module reads
the commit fields through its own minimal projection over the raw runs table and LEFT JOINs it on
``run_id`` — the ``head_commit`` JSON is ``ifNull``-unwrapped before ``JSONExtractString``
because a Nullable column can't feed the extractor.

Two PR keys, by design: ``pr_number`` is the runs builder's association-derived number (0 when the
run has no ``pull_requests`` association — pushes to master, fork PRs), and ``commit_pr_number`` is
parsed from the squash-merge message's ``(#NNNN)`` suffix. The latter is how a master push run gets
PR attribution at all, since its ``pull_requests`` association is empty (SPEC §7).

``created_at_raw`` is the unparsed jobs ``created_at`` string riding alongside the parsed
``created_at``. Consumers windowing this view pair their precise ``created_at`` bound with a coarse
``created_at_raw >= '<YYYY-MM-DD>'`` floor a day below the window — ISO strings compare
lexicographically, and a raw-string predicate is the only one the parquet scan can prune on (a
parsed-column predicate hits a computed column and forces a full scan). ``created_at`` stays the
precise filter; the raw twin just lets the jobs scan skip.

Nothing here is registered as a global HogQL view; it is provisioned per-team as a non-materialized
``DataWarehouseSavedQuery`` by data_modeling's managed-viewset sync (kind ``engineering_analytics``).
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import DateTimeDatabaseField, FieldOrTable, IntegerDatabaseField, StringDatabaseField

from products.engineering_analytics.backend.logic.sources import resolve_job_cost_source_pairs
from products.engineering_analytics.backend.logic.views import workflow_jobs, workflow_runs

if TYPE_CHECKING:
    from posthog.models.team import Team

# Public view name — stable contract for insights, subscriptions, other products, and execute-sql.
VIEW_NAME = "engineering_analytics_ci_job_history"

# Public column contract (order fixes the UNION ALL column order across sources and the saved-query
# schema). ``nullable=True`` on the columns that can genuinely be NULL (the parsed timestamps, a
# queued job's conclusion/completed_at, a run's raw head_sha, and commit_pr_number when there's no
# ``(#NNNN)``); the attribution columns stay nullable for parity with job_costs even though a join
# miss fills them with type defaults rather than NULL (see the module docstring).
FIELDS: dict[str, FieldOrTable] = {
    "repo_owner": StringDatabaseField(name="repo_owner", nullable=True),
    "repo_name": StringDatabaseField(name="repo_name", nullable=True),
    "workflow_name": StringDatabaseField(name="workflow_name"),
    "job_name": StringDatabaseField(name="job_name"),
    "run_id": IntegerDatabaseField(name="run_id"),
    "run_attempt": IntegerDatabaseField(name="run_attempt"),
    "head_branch": StringDatabaseField(name="head_branch"),
    "head_sha": StringDatabaseField(name="head_sha", nullable=True),
    "status": StringDatabaseField(name="status"),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
    "created_at_raw": StringDatabaseField(name="created_at_raw", nullable=True),
    "started_at": DateTimeDatabaseField(name="started_at", nullable=True),
    "completed_at": DateTimeDatabaseField(name="completed_at", nullable=True),
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "pr_number": IntegerDatabaseField(name="pr_number", nullable=True),
    "commit_author_name": StringDatabaseField(name="commit_author_name", nullable=True),
    "commit_author_email": StringDatabaseField(name="commit_author_email", nullable=True),
    "commit_message": StringDatabaseField(name="commit_message", nullable=True),
    "commit_pr_number": IntegerDatabaseField(name="commit_pr_number", nullable=True),
}


def _head_commit_query(runs_table: str) -> str:
    """The run's commit attribution, keyed on ``run_id`` alone — attribution is attempt-invariant.

    ``ifNull``-unwraps the Nullable ``head_commit`` JSON to ``'{}'`` before extracting, so a run
    with no landed commit object yields empty strings rather than a Nullable-into-extractor error.
    """
    return f"""
        SELECT
            run_id,
            JSONExtractString(head_commit, 'author', 'name') AS commit_author_name,
            JSONExtractString(head_commit, 'author', 'email') AS commit_author_email,
            JSONExtractString(head_commit, 'message') AS commit_message
        FROM (
            SELECT
                id AS run_id,
                ifNull(head_commit, '{{}}') AS head_commit
            FROM {runs_table}
        )
    """


def build_query(*, jobs_table: str, runs_table: str) -> str:
    """The per-job-attempt history SELECT for one GitHub source: curated jobs LEFT JOIN curated runs,
    plus the run's commit attribution.

    Two layers so ``commit_pr_number`` can be derived from ``commit_message``: the inner join layer
    projects the raw columns (including ``commit_message`` from the head-commit projection), and the
    outer layer extracts the squash-merge PR number off that projected column — a same-SELECT alias
    can't feed another expression, so the extraction lives one level up.
    """
    jobs = workflow_jobs.build_query(jobs_table)
    runs = workflow_runs.build_query(runs_table)
    head_commits = _head_commit_query(runs_table)

    return f"""
        SELECT
            repo_owner,
            repo_name,
            workflow_name,
            job_name,
            run_id,
            run_attempt,
            head_branch,
            head_sha,
            status,
            conclusion,
            created_at,
            created_at_raw,
            started_at,
            completed_at,
            duration_seconds,
            pr_number,
            commit_author_name,
            commit_author_email,
            commit_message,
            -- Anchored to a line end ((?m) — the squash title): an unanchored match would take the
            -- FIRST (#N) in the message, misattributing reverts ('Revert "x (#A)" (#B)') to the
            -- reverted PR instead of the reverting one.
            accurateCastOrNull(regexpExtract(commit_message, '(?m)[(]#([0-9]+)[)]$'), 'Int64') AS commit_pr_number
        FROM (
            SELECT
                r.repo_owner AS repo_owner,
                r.repo_name AS repo_name,
                j.workflow_name AS workflow_name,
                j.name AS job_name,
                j.run_id AS run_id,
                j.run_attempt AS run_attempt,
                j.head_branch AS head_branch,
                r.head_sha AS head_sha,
                j.status AS status,
                j.conclusion AS conclusion,
                j.created_at AS created_at,
                j.created_at_raw AS created_at_raw,
                j.started_at AS started_at,
                j.completed_at AS completed_at,
                j.duration_seconds AS duration_seconds,
                -- The runs builder emits 0 for a run with no PR association; keep that semantic (a
                -- LEFT-JOIN miss also reads 0 — type default). commit_pr_number is the push-run fallback.
                r.pr_number AS pr_number,
                hc.commit_author_name AS commit_author_name,
                hc.commit_author_email AS commit_author_email,
                hc.commit_message AS commit_message
            FROM ({jobs}) AS j
            LEFT JOIN ({runs}) AS r ON j.run_id = r.id
            LEFT JOIN ({head_commits}) AS hc ON j.run_id = hc.run_id
        )
    """


def build_team_view(team: "Team") -> str | None:
    """The full view body for a team: every GitHub source with both runs and jobs synced, unioned.

    None when the team has no qualifying source (no view is created). Gated on the same
    ``resolve_job_cost_source_pairs`` condition as ``job_costs`` so the exposed views stay coherent.
    """
    pairs = resolve_job_cost_source_pairs(team)
    if not pairs:
        return None
    selects = [build_query(jobs_table=jobs_table, runs_table=runs_table) for jobs_table, runs_table in pairs]
    return "\nUNION ALL\n".join(selects)
