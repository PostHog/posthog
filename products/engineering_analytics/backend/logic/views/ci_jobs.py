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
from products.engineering_analytics.backend.logic.views import job_costs, stored_view, workflow_jobs

if TYPE_CHECKING:
    from posthog.models.team import Team

VIEW_NAME = "engineering_analytics_ci_jobs"

REBUILT_AFTER = (WORKFLOW_JOBS_SCHEMA, DEPOT_JOB_ATTEMPTS_SCHEMA)

WINDOW = stored_view.STORED_JOBS_WINDOW

FIELDS: dict[str, FieldOrTable] = {**job_costs.BUILDER_FIELDS, **stored_view.IDENTITY_FIELDS}

_STORED_AS = {"name": "job_name", "head_branch": "job_head_branch"}


def build_source_query(source: JobSourceTables) -> str:
    """The view rows of one repository: the jobs created inside ``WINDOW``."""
    # The cost builder joins every run it is given, so without this floor a rebuild parses the whole
    # run history.
    runs = (
        f"(SELECT * FROM {source.runs_source} "
        f"WHERE run_started_at >= {raw_date_floor(stored_view.STORED_JOB_RUNS_WINDOW)})"
    )
    jobs = job_costs.build_query(jobs_table=source.jobs_source, runs_table=runs, created_floor=True).replace(
        "{job_created_floor}", raw_date_floor(WINDOW)
    )
    return stored_view.build_source_view(source, job_costs.BUILDER_FIELDS, jobs)


def build_team_view(team: "Team") -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    return stored_view.build_team_view(team, build_source_query)


def build_jobs_read_query(*, source_id: str, repository: str) -> str:
    """One repository's stored rows in the shape the jobs builder returns."""
    columns = [
        stored_view.stored_column(name, FIELDS[_STORED_AS.get(name, name)], stored_as=_STORED_AS.get(name))
        for name in workflow_jobs.COLUMNS
    ]
    return f"SELECT {', '.join(columns)} FROM {_rows(source_id, repository)}"


def build_job_costs_read_query(*, source_id: str, repository: str) -> str:
    """One repository's stored rows in the shape the cost builder returns."""
    columns = [stored_view.stored_column(name, field) for name, field in job_costs.BUILDER_FIELDS.items()]
    return f"SELECT {', '.join(columns)} FROM {_rows(source_id, repository)}"


def _rows(source_id: str, repository: str) -> str:
    return stored_view.stored_rows(VIEW_NAME, source_id=source_id, repository=repository)
