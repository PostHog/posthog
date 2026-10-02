"""Curated CI runs view: one row per workflow run, GitHub Actions and Depot CI together.

The rows are the output of the ``workflow_runs`` builder, so attribution, the merge-queue rule and the
hand-off shell filter are the ones every product read uses. The view is materialized: a read takes the
parsed rows from one table, instead of parsing every run payload and repeating the shell filter in
each query.

It leaves out ``stopped_reporting``, the one builder column that depends on the clock. A stored row
would keep the answer of its last rebuild, so a reader derives it from ``status`` and ``updated_at``.

It keeps a rolling window (see ``stored_window``), so a rebuild costs the same as the history grows.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
)

from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_stored_view_sources
from products.engineering_analytics.backend.logic.views import workflow_runs
from products.engineering_analytics.backend.logic.views.stored_window import STORED_RUNS_WINDOW, raw_date_floor

if TYPE_CHECKING:
    from posthog.models.team import Team

VIEW_NAME = "engineering_analytics_ci_runs"

# Column order is the saved-query schema and the UNION ALL order across sources: append, never reorder.
FIELDS: dict[str, FieldOrTable] = {
    "id": IntegerDatabaseField(name="id"),
    "workflow_name": StringDatabaseField(name="workflow_name", nullable=True),
    "head_sha": StringDatabaseField(name="head_sha", nullable=True),
    "head_branch": StringDatabaseField(name="head_branch", nullable=True),
    "status": StringDatabaseField(name="status", nullable=True),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "run_started_at": DateTimeDatabaseField(name="run_started_at", nullable=True),
    "updated_at": DateTimeDatabaseField(name="updated_at", nullable=True),
    "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
    "run_attempt": IntegerDatabaseField(name="run_attempt", nullable=True),
    "is_merge_queue": BooleanDatabaseField(name="is_merge_queue"),
    # 0 when the run has no pull request (a default-branch push, a fork run).
    "pr_number": IntegerDatabaseField(name="pr_number"),
    "commit_pr_number": IntegerDatabaseField(name="commit_pr_number", nullable=True),
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "repo_owner": StringDatabaseField(name="repo_owner"),
    "repo_name": StringDatabaseField(name="repo_name"),
    "ci_engine": StringDatabaseField(name="ci_engine"),
    "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
    "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
    "source_id": StringDatabaseField(name="source_id"),
    "repository": StringDatabaseField(name="repository"),
}

BUILDER_COLUMNS = tuple(name for name in FIELDS if name not in ("source_id", "repository"))


def build_source_query(source: JobSourceTables) -> str:
    """The view rows of one repository: the runs that started inside ``STORED_RUNS_WINDOW``."""
    runs = workflow_runs.build_query(
        source.runs_source, pull_requests_table=source.pull_requests, started_floor=True
    ).replace("{run_started_floor}", raw_date_floor(STORED_RUNS_WINDOW))
    return f"SELECT {', '.join(BUILDER_COLUMNS)}, {source.identity_columns} FROM ({runs})"


def build_team_view(team: "Team") -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    sources = resolve_stored_view_sources(team)
    if not sources:
        return None
    return "\nUNION ALL\n".join(build_source_query(source) for source in sources)
