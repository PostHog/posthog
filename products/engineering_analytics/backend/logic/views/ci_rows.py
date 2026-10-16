"""The stored CI rows: two materialized managed views, one per grain, that data modeling updates
in place every 15 minutes. SPEC.md section 5 has the design.
"""

from collections.abc import Callable
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

from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_job_source_tables
from products.engineering_analytics.backend.logic.views import depot_ci, job_costs, workflow_jobs, workflow_runs

if TYPE_CHECKING:
    from posthog.models.team import Team

RUNS_VIEW_NAME = "engineering_analytics_ci_runs"
JOBS_VIEW_NAME = "engineering_analytics_ci_jobs"

SYNC_FREQUENCY = timedelta(minutes=15)

# Almost every run settles within a day of its creation, so two days of lookback re-read the few
# that settle later without re-reading much. A run that settles later than that is read again only
# by a full build.
LOOKBACK = timedelta(days=2)


# The parsed ``created_at`` is the key. Depot lists a job's last attempt again under every later
# attempt of its run, so a job id alone names several rows there.
INCREMENTAL_CONFIG: dict[str, Any] = {
    "enabled": True,
    "incremental_key": "created_at",
    "unique_key": ["ci_engine", "id", "run_attempt"],
    "lookback_seconds": int(LOOKBACK.total_seconds()),
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
}

RUN_COLUMNS = tuple(column for column in RUN_FIELDS if column not in _SOURCE_FIELDS)
JOB_COLUMNS = tuple(column for column in JOB_FIELDS if column not in _SOURCE_FIELDS)
assert JOB_COLUMNS == (*workflow_jobs.COLUMNS, *job_costs.COST_COLUMNS)


def _stored_rows(source: JobSourceTables, columns: tuple[str, ...], rows: str) -> str:
    # GitHub names are case-insensitive, and a source can store them in either case.
    return f"""
        SELECT
            {escape_hogql_string(source.source_id)} AS source_id,
            {escape_hogql_string(source.repository.casefold())} AS repository,
            {", ".join(columns)}
        FROM ({rows})
    """


def runs_select(source: JobSourceTables) -> str:
    runs = depot_ci.stored_runs(
        source.github_workflow_runs,
        source.depot_job_attempts,
        source.pull_requests,
        source.github_workflow_jobs,
        optional_columns=source.workflow_runs_optional_columns,
    )
    rows = workflow_runs.build_query(
        runs, pull_requests_table=source.pull_requests, passthrough=depot_ci.STORED_RUN_COLUMNS
    )
    return _stored_rows(source, RUN_COLUMNS, rows)


def jobs_select(source: JobSourceTables) -> str:
    jobs = depot_ci.stored_jobs(source.github_workflow_jobs, source.depot_job_attempts)
    rows = job_costs.build_costed_jobs_query(workflow_jobs.build_query(jobs))
    return _stored_rows(source, JOB_COLUMNS, rows)


def build_team_views(team: "Team") -> tuple[str, str] | None:
    """The runs view and the jobs view over every qualifying source of the team, or None when
    there is none."""
    sources = resolve_job_source_tables(team)
    if not sources:
        return None
    return _union(sources, runs_select), _union(sources, jobs_select)


def _union(sources: list[JobSourceTables], select: Callable[[JobSourceTables], str]) -> str:
    return "\nUNION ALL\n".join(select(source) for source in sources)
