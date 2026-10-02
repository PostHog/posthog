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

# The tables whose load makes the view out of date. The view also reads the runs, and takes those
# rows as of their last load.
REBUILT_AFTER = (WORKFLOW_JOBS_SCHEMA, DEPOT_JOB_ATTEMPTS_SCHEMA)

# Column order is the saved-query schema and the UNION ALL order across sources: append, never reorder.
FIELDS: dict[str, FieldOrTable] = {**job_costs.BUILDER_FIELDS, **stored_view.IDENTITY_FIELDS}


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
    return stored_view.build_source_view(source, FIELDS, jobs)


def build_team_view(team: "Team") -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    return stored_view.build_team_view(team, build_source_query)
