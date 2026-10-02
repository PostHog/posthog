"""Curated CI jobs view: one row per job attempt with its cost, GitHub Actions and Depot CI together.

The rows are the output of the ``job_costs`` builder with every column of the jobs builder kept, so the
one table serves a read of job rows as well as a read of job costs. The view is materialized: a read
takes the parsed rows from the table, instead of parsing every job payload, joining the runs and
repeating the hand-off shell filter in each query.

The public ``engineering_analytics_job_costs`` view stays computed at query time, so its contract
does not change.

It keeps a rolling window (see ``stored_window``), so a rebuild costs the same as the history grows.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import DateTimeDatabaseField, FieldOrTable, IntegerDatabaseField, StringDatabaseField

from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_stored_view_sources
from products.engineering_analytics.backend.logic.views import job_costs
from products.engineering_analytics.backend.logic.views.stored_window import STORED_JOBS_WINDOW, raw_date_floor

if TYPE_CHECKING:
    from posthog.models.team import Team

VIEW_NAME = "engineering_analytics_ci_jobs"

# Column order is the saved-query schema and the UNION ALL order across sources: append, never reorder.
FIELDS: dict[str, FieldOrTable] = {
    **job_costs.FIELDS,
    # NULL for a job whose run row is missing, like the other attribution columns.
    "run_started_at": DateTimeDatabaseField(name="run_started_at", nullable=True),
    "run_head_branch": StringDatabaseField(name="run_head_branch", nullable=True),
    "id": IntegerDatabaseField(name="id"),
    "head_sha": StringDatabaseField(name="head_sha"),
    "labels": StringDatabaseField(name="labels"),
    "provisioning_seconds": IntegerDatabaseField(name="provisioning_seconds", nullable=True),
    # The job's own branch. ``head_branch`` falls back to the run's.
    "job_head_branch": StringDatabaseField(name="job_head_branch"),
    "source_id": StringDatabaseField(name="source_id"),
    "repository": StringDatabaseField(name="repository"),
}


def build_source_query(source: JobSourceTables) -> str:
    """The view rows of one repository: the jobs created inside ``STORED_JOBS_WINDOW``."""
    jobs = job_costs.build_query(
        jobs_table=source.jobs_source,
        runs_table=source.runs_source,
        include_run_columns=True,
        include_job_columns=True,
        created_floor=True,
    ).replace("{job_created_floor}", raw_date_floor(STORED_JOBS_WINDOW))
    return f"SELECT *, {source.identity_columns} FROM ({jobs})"


def build_team_view(team: "Team") -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    sources = resolve_stored_view_sources(team)
    if not sources:
        return None
    return "\nUNION ALL\n".join(build_source_query(source) for source in sources)
