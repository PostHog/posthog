"""Curated per-job CI cost view — the one warehouse view this product exposes.

Composes the curated ``workflow_jobs`` and ``workflow_runs`` builders (one row per job attempt)
and renders the Depot cost model from ``logic.cost`` as ClickHouse expressions, so
``provider`` / ``os`` / ``vcpu`` / ``multiplier`` / ``billable_seconds`` / ``estimated_cost_usd``
are computed at query time from the same constants the Python model uses. The cost model stays
defined once in ``logic.cost``; this module only wires its rendered expressions over the join.

``build_query`` produces the SELECT for one GitHub source; ``build_team_view`` unions every
qualifying source into the single view body. The join is a LEFT JOIN (all jobs are kept — a job
whose run row is missing keeps NULL attribution) rather than the INNER join the per-PR cost
queries use, because the view is the full per-job substrate, not a PR-scoped rollup.

Nothing here is registered as a global HogQL view; the view is provisioned per-team as a
non-materialized ``DataWarehouseSavedQuery`` by data_modeling's managed-viewset sync.
"""

from typing import TYPE_CHECKING

from products.engineering_analytics.backend.logic.cost import (
    render_billable_seconds,
    render_estimated_cost_usd,
    render_multiplier,
    render_os,
    render_provider,
    render_vcpu,
)
from products.engineering_analytics.backend.logic.sources import resolve_job_cost_source_pairs
from products.engineering_analytics.backend.logic.views import workflow_jobs, workflow_runs

if TYPE_CHECKING:
    from posthog.models.team import Team

# Public view name — stable contract for insights, subscriptions, other products, and execute-sql.
VIEW_NAME = "engineering_analytics_job_costs"

# Public column contract (order matters — it fixes the UNION ALL column order across sources and
# the saved-query schema). ``hogql`` is the STR_TO_HOGQL_MAPPING field-class name data_modeling
# resolves; ``clickhouse`` is the best-effort storage type. Nullable where the LEFT JOIN or the
# cost model can produce NULL (unjoined run → NULL attribution; unclassified/non-billable job →
# NULL cost).
COLUMNS: dict[str, dict[str, str]] = {
    "repo_owner": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
    "repo_name": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
    "pr_number": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "workflow_name": {"hogql": "StringDatabaseField", "clickhouse": "String"},
    "job_name": {"hogql": "StringDatabaseField", "clickhouse": "String"},
    "run_id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"},
    "run_attempt": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"},
    "head_branch": {"hogql": "StringDatabaseField", "clickhouse": "String"},
    "status": {"hogql": "StringDatabaseField", "clickhouse": "String"},
    "conclusion": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
    "runner_name": {"hogql": "StringDatabaseField", "clickhouse": "String"},
    "created_at": {"hogql": "DateTimeDatabaseField", "clickhouse": "Nullable(DateTime64(6, 'UTC'))"},
    "started_at": {"hogql": "DateTimeDatabaseField", "clickhouse": "Nullable(DateTime64(6, 'UTC'))"},
    "completed_at": {"hogql": "DateTimeDatabaseField", "clickhouse": "Nullable(DateTime64(6, 'UTC'))"},
    "queue_seconds": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "duration_seconds": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "provider": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
    "os": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
    "vcpu": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "multiplier": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "billable_seconds": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
    "estimated_cost_usd": {"hogql": "FloatDatabaseField", "clickhouse": "Nullable(Float64)"},
}


def build_query(*, jobs_table: str, runs_table: str) -> str:
    """The per-job cost SELECT for one GitHub source: curated jobs LEFT JOIN curated runs.

    Grain is one row per job attempt (a retry appears once per attempt — correct for cost). The
    cost columns are derived only from the job's ``labels`` + elapsed, so an unjoined run (no ``r``
    row) leaves only the attribution columns (``repo_owner`` / ``repo_name`` / ``pr_number``) NULL.
    """
    jobs = workflow_jobs.build_query(jobs_table)
    runs = workflow_runs.build_query(runs_table)

    # labels is already ifNull'd to '[]' by the jobs builder; JSONExtract to Array(String) yields
    # [] for any non-array/invalid JSON, matching cost._parse_labels' empty-on-bad-input behavior.
    labels_array = "JSONExtract(labels, 'Array(String)')"

    return f"""
        SELECT
            repo_owner,
            repo_name,
            pr_number,
            workflow_name,
            job_name,
            run_id,
            run_attempt,
            head_branch,
            status,
            conclusion,
            runner_name,
            created_at,
            started_at,
            completed_at,
            queue_seconds,
            duration_seconds,
            provider,
            os,
            vcpu,
            {render_multiplier("vcpu")} AS multiplier,
            {render_billable_seconds("provider", "os", "duration_seconds")} AS billable_seconds,
            {render_estimated_cost_usd("provider", "os", "vcpu", "duration_seconds")} AS estimated_cost_usd
        FROM (
            SELECT
                repo_owner,
                repo_name,
                pr_number,
                workflow_name,
                job_name,
                run_id,
                run_attempt,
                head_branch,
                status,
                conclusion,
                runner_name,
                created_at,
                started_at,
                completed_at,
                queue_seconds,
                duration_seconds,
                {render_provider("labels_arr")} AS provider,
                {render_os("labels_arr")} AS os,
                {render_vcpu("labels_arr")} AS vcpu
            FROM (
                SELECT
                    r.repo_owner AS repo_owner,
                    r.repo_name AS repo_name,
                    -- An unattributed run surfaces pr_number 0 in the runs builder; normalize both
                    -- that and the LEFT-JOIN NULL to NULL so a missing PR is never read as PR #0.
                    nullIf(r.pr_number, 0) AS pr_number,
                    j.workflow_name AS workflow_name,
                    j.name AS job_name,
                    j.run_id AS run_id,
                    j.run_attempt AS run_attempt,
                    j.head_branch AS head_branch,
                    j.status AS status,
                    j.conclusion AS conclusion,
                    j.runner_name AS runner_name,
                    j.created_at AS created_at,
                    j.started_at AS started_at,
                    j.completed_at AS completed_at,
                    j.queue_seconds AS queue_seconds,
                    j.duration_seconds AS duration_seconds,
                    {labels_array} AS labels_arr
                FROM ({jobs}) AS j
                LEFT JOIN ({runs}) AS r ON j.run_id = r.id AND j.run_attempt = r.run_attempt
            )
        )
    """


def build_team_view(team: "Team") -> str | None:
    """The full view body for a team: every GitHub source with both runs and jobs synced, unioned.

    None when the team has no qualifying source (no view is created). One view over all sources so
    the exposed name stays stable regardless of how many GitHub sources a team connects.
    """
    pairs = resolve_job_cost_source_pairs(team)
    if not pairs:
        return None
    selects = [build_query(jobs_table=jobs_table, runs_table=runs_table) for jobs_table, runs_table in pairs]
    return "\nUNION ALL\n".join(selects)
