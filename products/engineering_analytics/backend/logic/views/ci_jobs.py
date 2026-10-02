"""Stored CI jobs view: one row per job attempt with its cost, GitHub Actions and Depot CI together.

The rows are every column of the ``job_costs`` builder, which include every column of the jobs
builder, so one table answers a read of job rows and a read of job costs. The view is materialized,
so its table holds the parsed and joined rows.

The public ``engineering_analytics_job_costs`` view does not read this table.

It keeps a rolling window (see ``stored_view``), so a rebuild costs the same as the history grows.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import FieldOrTable

from products.engineering_analytics.backend.logic.queries._workflow_filters import raw_date_floor
from products.engineering_analytics.backend.logic.sources import (
    DEPOT_JOB_ATTEMPTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    JobSourceTables,
)
from products.engineering_analytics.backend.logic.views import job_costs, stored_view

if TYPE_CHECKING:
    from posthog.models.team import Team

VIEW_NAME = "engineering_analytics_ci_jobs"

REBUILT_AFTER = (WORKFLOW_JOBS_SCHEMA, DEPOT_JOB_ATTEMPTS_SCHEMA)

FIELDS: dict[str, FieldOrTable] = {**job_costs.BUILDER_FIELDS, **stored_view.IDENTITY_FIELDS}

# The jobs builder's columns in its order, each with the stored column that holds it. The cost
# builder renames two of them, because its own ``head_branch`` falls back to the run's.
_JOBS_BUILDER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("run_id", "run_id"),
    ("run_attempt", "run_attempt"),
    ("name", "job_name"),
    ("workflow_name", "workflow_name"),
    ("head_sha", "head_sha"),
    ("head_branch", "job_head_branch"),
    ("status", "status"),
    ("conclusion", "conclusion"),
    ("labels", "labels"),
    ("runner_name", "runner_name"),
    ("created_at", "created_at"),
    ("created_at_raw", "created_at_raw"),
    ("started_at", "started_at"),
    ("completed_at", "completed_at"),
    ("duration_seconds", "duration_seconds"),
    ("queue_seconds", "queue_seconds"),
    ("provisioning_seconds", "provisioning_seconds"),
    ("is_rerun_copy", "is_rerun_copy"),
    ("ci_engine", "ci_engine"),
    ("native_run_id", "native_run_id"),
    ("native_workflow_run_id", "native_workflow_run_id"),
    ("native_job_id", "native_job_id"),
    ("native_attempt_id", "native_attempt_id"),
)


def build_source_query(source: JobSourceTables) -> str:
    """The view rows of one repository: the jobs created inside ``STORED_JOBS_WINDOW``."""
    # The cost builder joins every run it is given, so without this floor a rebuild parses the whole
    # run history.
    runs = (
        f"(SELECT * FROM {source.runs_source} "
        f"WHERE run_started_at >= {raw_date_floor(stored_view.STORED_JOB_RUNS_WINDOW)})"
    )
    jobs = job_costs.build_query(jobs_table=source.jobs_source, runs_table=runs, created_floor=True).replace(
        "{job_created_floor}", raw_date_floor(stored_view.STORED_JOBS_WINDOW)
    )
    return stored_view.build_source_view(source, job_costs.BUILDER_FIELDS, jobs)


def build_team_view(team: "Team") -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    return stored_view.build_team_view(team, build_source_query)


def build_jobs_read_query(rows: str) -> str:
    """The stored ``rows`` in the shape the jobs builder returns, for a product read."""
    columns = [
        stored_view.stored_column(name, FIELDS[stored_as], stored_as=stored_as)
        for name, stored_as in _JOBS_BUILDER_COLUMNS
    ]
    return f"SELECT {', '.join(columns)} FROM {rows}"


def build_job_costs_read_query(rows: str) -> str:
    """The stored ``rows`` in the shape the cost builder returns, for a product read."""
    columns = [stored_view.stored_column(name, field) for name, field in job_costs.BUILDER_FIELDS.items()]
    return f"SELECT {', '.join(columns)} FROM {rows}"
