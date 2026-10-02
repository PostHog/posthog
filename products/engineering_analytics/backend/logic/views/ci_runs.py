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

REBUILT_AFTER = (WORKFLOW_RUNS_SCHEMA, DEPOT_JOB_ATTEMPTS_SCHEMA)

WINDOW = stored_view.STORED_RUNS_WINDOW

_BEFORE_STOPPED_REPORTING = "duration_seconds"

_BUILDER_FIELDS: dict[str, FieldOrTable] = {
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
    "pr_number": IntegerDatabaseField(name="pr_number"),
    "commit_pr_number": IntegerDatabaseField(name="commit_pr_number", nullable=True),
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "repo_owner": StringDatabaseField(name="repo_owner"),
    "repo_name": StringDatabaseField(name="repo_name"),
    "ci_engine": StringDatabaseField(name="ci_engine"),
    "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
    "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
}

FIELDS: dict[str, FieldOrTable] = {**_BUILDER_FIELDS, **stored_view.IDENTITY_FIELDS}


def build_source_query(source: JobSourceTables) -> str:
    """The view rows of one repository: the runs that started inside ``WINDOW``."""
    runs = workflow_runs.build_query(
        source.runs_source, pull_requests_table=source.pull_requests, started_floor=True
    ).replace("{run_started_floor}", raw_date_floor(WINDOW))
    return stored_view.build_source_view(source, _BUILDER_FIELDS, runs)


def build_team_view(team: "Team") -> str | None:
    """The view body for a team, or None when no repository has both runs and jobs synced."""
    return stored_view.build_team_view(team, build_source_query)


def build_read_query(*, source_id: str, repository: str) -> str:
    """One repository's stored rows in the shape the runs builder returns. It adds
    ``stopped_reporting`` back, so the column follows the reader's clock."""
    columns: list[str] = []
    for name, field in _BUILDER_FIELDS.items():
        columns.append(stored_view.stored_column(name, field))
        if name == _BEFORE_STOPPED_REPORTING:
            columns.append(f"{workflow_runs.STOPPED_REPORTING_SQL} AS stopped_reporting")
    rows = stored_view.stored_rows(VIEW_NAME, source_id=source_id, repository=repository)
    return f"SELECT {', '.join(columns)} FROM {rows}"
