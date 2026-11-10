"""One row per job attempt with its estimated cost, rendered from the cost model in ``logic.cost``.

Jobs join runs on ``(ci_engine, run_id)`` and never on ``run_attempt``, because the runs snapshot
keeps only the newest attempt's row. Re-run copies stay as rows and carry no cost.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
)

from products.engineering_analytics.backend.logic.cost import (
    render_billable_seconds,
    render_billed_elapsed_seconds,
    render_depot_label,
    render_estimated_cost_usd,
    render_hosted_label,
    render_multiplier,
    render_os,
    render_provider,
    render_vcpu,
)
from products.engineering_analytics.backend.logic.sources import resolve_job_source_tables
from products.engineering_analytics.backend.logic.views import workflow_jobs, workflow_runs

if TYPE_CHECKING:
    from posthog.models.team import Team

# Saved queries and insights select this view by name, so a rename breaks them.
VIEW_NAME = "engineering_analytics_job_costs"

# The column order is the UNION ALL order across sources and the saved-query schema, so append new
# columns and never reorder.
FIELDS: dict[str, FieldOrTable] = {
    "repo_owner": StringDatabaseField(name="repo_owner", nullable=True),
    "repo_name": StringDatabaseField(name="repo_name", nullable=True),
    "pr_number": IntegerDatabaseField(name="pr_number", nullable=True),
    "workflow_name": StringDatabaseField(name="workflow_name"),
    "job_name": StringDatabaseField(name="job_name"),
    "run_id": IntegerDatabaseField(name="run_id"),
    "run_attempt": IntegerDatabaseField(name="run_attempt"),
    "head_branch": StringDatabaseField(name="head_branch"),
    "status": StringDatabaseField(name="status"),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "runner_name": StringDatabaseField(name="runner_name"),
    "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
    "started_at": DateTimeDatabaseField(name="started_at", nullable=True),
    "completed_at": DateTimeDatabaseField(name="completed_at", nullable=True),
    "queue_seconds": IntegerDatabaseField(name="queue_seconds", nullable=True),
    # The time from started_at to completed_at. Depot bills billable_seconds, not this.
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "provider": StringDatabaseField(name="provider", nullable=True),
    "os": StringDatabaseField(name="os", nullable=True),
    "vcpu": IntegerDatabaseField(name="vcpu", nullable=True),
    "multiplier": IntegerDatabaseField(name="multiplier", nullable=True),
    # duration_seconds minus the runner boot that precedes the first step. NULL when the row is not
    # billable (not Depot, not Linux, unclassified, or a re-run copy) or has not settled.
    "billable_seconds": IntegerDatabaseField(name="billable_seconds", nullable=True),
    "estimated_cost_usd": FloatDatabaseField(name="estimated_cost_usd", nullable=True),
    # A job whose run row is missing reads false.
    "is_merge_queue": BooleanDatabaseField(name="is_merge_queue"),
    # NULL cost has three causes, and each has its own column: provider for a tier that is not
    # billable, completed_at for an unsettled job, and this flag for a job that never executed.
    "is_rerun_copy": BooleanDatabaseField(name="is_rerun_copy"),
    # A predicate on the parsed created_at cannot prune the parquet scan, so a consumer pairs its
    # created_at bound with a coarse `created_at_raw >= '<YYYY-MM-DD>'` floor.
    "created_at_raw": StringDatabaseField(name="created_at_raw", nullable=True),
    "ci_engine": StringDatabaseField(name="ci_engine", nullable=True),
    "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
    "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
    "native_job_id": StringDatabaseField(name="native_job_id", nullable=True),
    "native_attempt_id": StringDatabaseField(name="native_attempt_id", nullable=True),
}


_PASSTHROUGH: tuple[tuple[str, DatabaseField], ...] = (
    # Run columns that the endpoint queries read and the public view leaves out.
    ("r.run_started_at", DateTimeDatabaseField(name="run_started_at", nullable=True)),
    ("r.head_branch", StringDatabaseField(name="run_head_branch", nullable=True)),
)

BUILDER_FIELDS: dict[str, FieldOrTable] = {**FIELDS, **{field.name: field for _, field in _PASSTHROUGH}}

_PASSTHROUGH_DEFS = "".join(f",\n            {expr} AS {field.name}" for expr, field in _PASSTHROUGH)

COST_COLUMNS = ("provider", "os", "vcpu", "multiplier", "billable_seconds", "estimated_cost_usd")


def build_query(*, jobs_table: workflow_jobs.JobsTable, runs_table: str, created_floor: bool = False) -> str:
    """The ``BUILDER_FIELDS`` columns for one source, one row per job attempt.

    A job whose run row is missing keeps its cost and reads NULL ``pr_number``.

    With ``created_floor``, the caller registers ``{job_created_floor}``. Every windowed query should
    pass it, because a window on run attributes cannot prune the jobs scan, and without a floor the
    ``is_rerun_copy`` duplicate scan reads the team's whole job history.
    """
    costed_jobs = build_costed_jobs_query(workflow_jobs.build_query(jobs_table, created_floor=created_floor))
    return build_attributed_query(costed_jobs=costed_jobs, runs=workflow_runs.build_query(runs_table))


def build_costed_jobs_query(jobs: str) -> str:
    """The rows of ``jobs`` with ``COST_COLUMNS`` added. ``jobs`` has the ``workflow_jobs.COLUMNS``
    columns.

    The cost of a job reads no column of its run, so a stored job row can carry it.
    """
    job_columns = ", ".join(workflow_jobs.COLUMNS)
    # JSONExtract yields [] for invalid JSON, which matches cost._parse_labels.
    labels_array = "JSONExtract(labels, 'Array(String)')"
    billed_seconds = render_billed_elapsed_seconds("duration_seconds", "provisioning_seconds")
    return f"""
        SELECT
            {job_columns},
            provider,
            os,
            vcpu,
            {render_multiplier("vcpu")} AS multiplier,
            {render_billable_seconds("provider", "os", "is_rerun_copy", "billed_seconds")} AS billable_seconds,
            {render_estimated_cost_usd("provider", "os", "vcpu", "is_rerun_copy", "billed_seconds")} AS estimated_cost_usd
        FROM (
            SELECT
                {job_columns},
                billed_seconds,
                {render_provider("depot_label", "hosted_label")} AS provider,
                {render_os("depot_label", "hosted_label")} AS os,
                {render_vcpu("depot_label", "hosted_label")} AS vcpu
            FROM (
                SELECT
                    {job_columns},
                    billed_seconds,
                    {render_depot_label("labels_arr")} AS depot_label,
                    {render_hosted_label("labels_arr")} AS hosted_label
                FROM (
                    SELECT
                        {job_columns},
                        -- What Depot actually bills: the wall-clock minus the runner boot GitHub
                        -- stamps into it. duration_seconds stays the full window for queue/duration UX.
                        {billed_seconds} AS billed_seconds,
                        {labels_array} AS labels_arr
                    FROM ({jobs})
                )
            )
        )
    """


def build_attributed_query(*, costed_jobs: str, runs: str) -> str:
    """The ``BUILDER_FIELDS`` columns: costed job rows with the attribution of their runs.

    The join reads the run row as it is now, so a re-run that moves the start of a run moves every
    job of that run with it.
    """
    return f"""
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
            {workflow_jobs.branch("j", "r")} AS head_branch,
            j.status AS status,
            j.conclusion AS conclusion,
            j.runner_name AS runner_name,
            j.created_at AS created_at,
            j.started_at AS started_at,
            j.completed_at AS completed_at,
            j.queue_seconds AS queue_seconds,
            j.duration_seconds AS duration_seconds,
            j.provider AS provider,
            j.os AS os,
            j.vcpu AS vcpu,
            j.multiplier AS multiplier,
            j.billable_seconds AS billable_seconds,
            j.estimated_cost_usd AS estimated_cost_usd,
            r.is_merge_queue AS is_merge_queue,
            j.is_rerun_copy AS is_rerun_copy,
            j.created_at_raw AS created_at_raw,
            j.ci_engine AS ci_engine,
            j.native_run_id AS native_run_id,
            j.native_workflow_run_id AS native_workflow_run_id,
            j.native_job_id AS native_job_id,
            j.native_attempt_id AS native_attempt_id{_PASSTHROUGH_DEFS}
        FROM ({costed_jobs}) AS j
        LEFT JOIN ({runs}) AS r ON j.run_id = r.id AND j.ci_engine = r.ci_engine
    """


def build_team_view(team: "Team") -> str | None:
    """The view body over every source with runs and jobs synced, or None when the team has none."""
    sources = resolve_job_source_tables(team)
    if not sources:
        return None
    return "\nUNION ALL\n".join(
        f"SELECT {', '.join(FIELDS)} FROM ({build_query(jobs_table=source.jobs_source, runs_table=source.runs_source)})"
        for source in sources
    )
