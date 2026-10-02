"""Stored CI runs view: one row per workflow run, GitHub Actions and Depot CI together.

The rows are the output of the ``workflow_runs`` builder, so attribution, the merge-queue rule and the
hand-off shell filter are the ones every product read uses. The view is materialized, so its table
holds the parsed rows.

It leaves out ``stopped_reporting``, the one builder column that depends on the clock. A stored row
would keep the answer of its last rebuild, so a reader derives it from ``status`` and ``updated_at``.

It keeps a rolling window (see ``stored_view``), so a rebuild costs the same as the history grows.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
)

from products.engineering_analytics.backend.logic.queries._workflow_filters import raw_date_floor
from products.engineering_analytics.backend.logic.sources import (
    DEPOT_JOB_ATTEMPTS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    JobSourceTables,
)
from products.engineering_analytics.backend.logic.views import stored_view, workflow_runs

if TYPE_CHECKING:
    from posthog.models.team import Team

VIEW_NAME = "engineering_analytics_ci_runs"

# The tables whose load makes the view out of date. The view also reads the pull requests and the
# jobs, and takes those rows as of their last load.
REBUILT_AFTER = (WORKFLOW_RUNS_SCHEMA, DEPOT_JOB_ATTEMPTS_SCHEMA)

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
    **stored_view.IDENTITY_FIELDS,
}


def build_source_query(source: JobSourceTables) -> str:
    """The view rows of one repository: the runs that started inside ``STORED_RUNS_WINDOW``."""
    runs = workflow_runs.build_query(
        source.runs_source, pull_requests_table=source.pull_requests, started_floor=True
    ).replace("{run_started_floor}", raw_date_floor(stored_view.STORED_RUNS_WINDOW))
    return stored_view.build_source_view(source, FIELDS, runs)


def build_team_view(team: "Team") -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    return stored_view.build_team_view(team, build_source_query)
