"""The stored CI rows: a runs view and a jobs view that data modeling materializes and updates in
place. SPEC.md section 5 has the design.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
)
from posthog.hogql.escape_sql import escape_hogql_string

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_job_source_tables
from products.engineering_analytics.backend.logic.views import depot_ci, job_costs, workflow_jobs, workflow_runs
from products.engineering_analytics.backend.logic.views.materialized_columns import materialized_select

if TYPE_CHECKING:
    from posthog.models.team import Team

RUNS_VIEW_NAME = "engineering_analytics_ci_runs"
JOBS_VIEW_NAME = "engineering_analytics_ci_jobs"

SYNC_FREQUENCY = timedelta(minutes=15)

# A run that settles later than this after its creation keeps its stored snapshot until a full build.
LOOKBACK = timedelta(days=2)


_INCREMENTAL_CONFIG: dict[str, Any] = {
    "enabled": True,
    "incremental_key": "created_at",
    "lookback_seconds": int(LOOKBACK.total_seconds()),
}

# The run key lets a rerun replace the run's snapshot. The job key uses Depot's stable job ID, so a
# job that executes again under a new attempt ID replaces its carried-over copy.
RUN_INCREMENTAL_CONFIG = {**_INCREMENTAL_CONFIG, "unique_key": ["source_id", "ci_engine", "id"]}
JOB_INCREMENTAL_CONFIG = {
    **_INCREMENTAL_CONFIG,
    "unique_key": ["source_id", "ci_engine", "native_job_id", "run_attempt"],
}

_SOURCE_FIELDS: dict[str, FieldOrTable] = {
    "source_id": StringDatabaseField(name="source_id"),
    "repository": StringDatabaseField(name="repository"),
}

RUN_FIELDS: dict[str, FieldOrTable] = {
    **_SOURCE_FIELDS,
    "id": IntegerDatabaseField(name="id"),
    "workflow_name": StringDatabaseField(name="workflow_name"),
    "head_sha": StringDatabaseField(name="head_sha", nullable=True),
    "head_branch": StringDatabaseField(name="head_branch", nullable=True),
    "status": StringDatabaseField(name="status", nullable=True),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "run_started_at": DateTimeDatabaseField(name="run_started_at", nullable=True),
    "updated_at": DateTimeDatabaseField(name="updated_at", nullable=True),
    "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
    "run_attempt": IntegerDatabaseField(name="run_attempt", nullable=True),
    "is_merge_queue": BooleanDatabaseField(name="is_merge_queue"),
    "pr_number": IntegerDatabaseField(name="pr_number", nullable=True),
    "commit_pr_number": IntegerDatabaseField(name="commit_pr_number", nullable=True),
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "repo_owner": StringDatabaseField(name="repo_owner", nullable=True),
    "repo_name": StringDatabaseField(name="repo_name", nullable=True),
    "ci_engine": StringDatabaseField(name="ci_engine"),
    "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
    "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
    "workflow_id": IntegerDatabaseField(name="workflow_id", nullable=True),
    "event": StringDatabaseField(name="event", nullable=True),
    "created_at_raw": StringDatabaseField(name="created_at_raw"),
    "run_started_at_raw": StringDatabaseField(name="run_started_at_raw"),
    "is_handoff_shell": BooleanDatabaseField(name="is_handoff_shell"),
}

JOB_FIELDS: dict[str, FieldOrTable] = {
    **_SOURCE_FIELDS,
    "id": IntegerDatabaseField(name="id"),
    "run_id": IntegerDatabaseField(name="run_id"),
    "run_attempt": IntegerDatabaseField(name="run_attempt", nullable=True),
    "name": StringDatabaseField(name="name"),
    "workflow_name": StringDatabaseField(name="workflow_name"),
    "head_sha": StringDatabaseField(name="head_sha"),
    "head_branch": StringDatabaseField(name="head_branch"),
    "status": StringDatabaseField(name="status"),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "labels": StringDatabaseField(name="labels"),
    "runner_name": StringDatabaseField(name="runner_name"),
    "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
    "created_at_raw": StringDatabaseField(name="created_at_raw"),
    "started_at": DateTimeDatabaseField(name="started_at", nullable=True),
    "completed_at": DateTimeDatabaseField(name="completed_at", nullable=True),
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "queue_seconds": IntegerDatabaseField(name="queue_seconds", nullable=True),
    "provisioning_seconds": IntegerDatabaseField(name="provisioning_seconds", nullable=True),
    "is_rerun_copy": BooleanDatabaseField(name="is_rerun_copy"),
    "ci_engine": StringDatabaseField(name="ci_engine"),
    "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
    "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
    "native_job_id": StringDatabaseField(name="native_job_id", nullable=True),
    "native_attempt_id": StringDatabaseField(name="native_attempt_id", nullable=True),
    **{column: job_costs.FIELDS[column] for column in job_costs.COST_COLUMNS},
    "is_handoff_shell": BooleanDatabaseField(name="is_handoff_shell"),
}

RUN_COLUMNS = tuple(column for column in RUN_FIELDS if column not in _SOURCE_FIELDS)
JOB_COLUMNS = tuple(column for column in JOB_FIELDS if column not in _SOURCE_FIELDS)
assert JOB_COLUMNS == (*workflow_jobs.COLUMNS, *job_costs.COST_COLUMNS, "is_handoff_shell")


def _stored_rows(source: JobSourceTables, fields: dict[str, FieldOrTable], rows: str) -> str:
    row_fields = {name: field for name, field in fields.items() if name not in _SOURCE_FIELDS}
    # GitHub names are case-insensitive, and a source can store them in either case.
    return f"""
        SELECT
            {escape_hogql_string(source.source_id)} AS source_id,
            {escape_hogql_string(source.repository.casefold())} AS repository,
            {materialized_select(row_fields, "stored")}
        FROM ({rows}) AS stored
    """


def _stored_runs(source: JobSourceTables, *, full_history: bool = False) -> str:
    return depot_ci.stored_runs(
        source.github_workflow_runs,
        source.depot_job_attempts,
        source.pull_requests,
        source.github_workflow_jobs,
        optional_columns=source.workflow_runs_optional_columns,
        full_history=full_history,
    )


def runs_select(source: JobSourceTables) -> str:
    rows = workflow_runs.build_query(
        _stored_runs(source), pull_requests_table=source.pull_requests, passthrough=depot_ci.STORED_RUN_COLUMNS
    )
    return _stored_rows(source, RUN_FIELDS, rows)


def jobs_select(source: JobSourceTables) -> str:
    jobs = depot_ci.stored_jobs(source.github_workflow_jobs, source.depot_job_attempts)
    rows = job_costs.build_costed_jobs_query(workflow_jobs.build_query(jobs, compact_duplicates=False))
    if source.depot_job_attempts is not None:
        # A new retry job can belong to an old run, so the suppression lookup must cover run history.
        runs = _stored_runs(source, full_history=True)
        shell = f"(ci_engine, run_id) IN (SELECT ci_engine, id FROM {runs} WHERE is_handoff_shell)"
    else:
        shell = "0"
    rows = f"SELECT j.*, {shell} AS is_handoff_shell FROM ({rows}) AS j"
    return _stored_rows(source, JOB_FIELDS, rows)


@frozen
class CIViewQueries:
    runs: str
    jobs: str


def build_views(sources: Sequence[JobSourceTables]) -> CIViewQueries:
    """Both view bodies over ``sources``. The reader compares a stored definition against this
    output, so no other code may assemble either view."""
    return CIViewQueries(
        runs="\nUNION ALL\n".join(runs_select(source) for source in sources),
        jobs="\nUNION ALL\n".join(jobs_select(source) for source in sources),
    )


def build_team_views(team: "Team") -> CIViewQueries | None:
    """Both view bodies, or None when the team has no source with runs and jobs synced."""
    sources = resolve_job_source_tables(team)
    return build_views(sources) if sources else None
