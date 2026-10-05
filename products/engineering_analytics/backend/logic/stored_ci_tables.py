"""The two ClickHouse tables of stored CI rows, as HogQL tables.

They are in no shared HogQL catalog. Their rows are stored with no user and for every source of a
team, so a query that could name them would read past the per-table warehouse access control.
``add_stored_ci_tables`` adds them to the catalog of one curated read handle, which checks the
access of its reader before it reads them.
"""

from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    TableNode,
)

from posthog.clickhouse.preaggregation.engineering_analytics_ci_sql import (
    CI_JOBS_TABLE_BASE_NAME,
    CI_RUNS_TABLE_BASE_NAME,
)

_JOB_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "job_id": StringDatabaseField(
        name="job_id", description="Identifier of the lazy computation job that produced this row."
    ),
    "source_id": StringDatabaseField(
        name="source_id", description="Identifier of the data warehouse source the row came from."
    ),
    "repository": StringDatabaseField(name="repository", description="The repository as owner/name in lower case."),
    "ci_engine": StringDatabaseField(name="ci_engine", description="github_actions or depot_ci."),
}

_STORAGE_FIELDS: dict[str, FieldOrTable] = {
    "computed_at": DateTimeDatabaseField(
        name="computed_at", description="When this row was computed; also the ReplacingMergeTree version."
    ),
    "expires_at": DateDatabaseField(
        name="expires_at", description="Date when this row expires and is dropped via TTL."
    ),
}


class _EngineeringAnalyticsCIPrecomputedTable(Table):
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )


class EngineeringAnalyticsCIRunsPrecomputedTable(_EngineeringAnalyticsCIPrecomputedTable):
    description: str = (
        "Internal precomputed table of CI workflow runs, one row per run, stored from external "
        "data-warehouse tables into native ClickHouse for Engineering analytics."
    )

    fields: dict[str, FieldOrTable] = {
        **_JOB_FIELDS,
        "id": IntegerDatabaseField(name="id"),
        "workflow_name": StringDatabaseField(name="workflow_name", nullable=True),
        "head_sha": StringDatabaseField(name="head_sha", nullable=True),
        "head_branch": StringDatabaseField(name="head_branch", nullable=True),
        "status": StringDatabaseField(name="status", nullable=True),
        "conclusion": StringDatabaseField(name="conclusion", nullable=True),
        "run_started_at": DateTimeDatabaseField(name="run_started_at", nullable=True),
        "run_started_at_raw": StringDatabaseField(
            name="run_started_at_raw", description="The unparsed ISO-8601 start time, for a string scan floor."
        ),
        "updated_at": DateTimeDatabaseField(name="updated_at", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
        "run_attempt": IntegerDatabaseField(name="run_attempt", nullable=True),
        "is_merge_queue": BooleanDatabaseField(name="is_merge_queue"),
        "pr_number": IntegerDatabaseField(name="pr_number"),
        "commit_pr_number": IntegerDatabaseField(name="commit_pr_number", nullable=True),
        "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
        "repo_owner": StringDatabaseField(name="repo_owner"),
        "repo_name": StringDatabaseField(name="repo_name"),
        "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
        "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
        "is_handoff_shell": BooleanDatabaseField(
            name="is_handoff_shell",
            description="The run only handed its tests to the other CI engine, or only waited for that hand-off.",
        ),
        **_STORAGE_FIELDS,
    }

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return CI_RUNS_TABLE_BASE_NAME

    def to_printed_hogql(self) -> str:
        return CI_RUNS_TABLE_BASE_NAME


class EngineeringAnalyticsCIJobsPrecomputedTable(_EngineeringAnalyticsCIPrecomputedTable):
    description: str = (
        "Internal precomputed table of CI job attempts with their estimated cost, one row per attempt, "
        "stored from external data-warehouse tables into native ClickHouse for Engineering analytics."
    )

    fields: dict[str, FieldOrTable] = {
        **_JOB_FIELDS,
        "id": IntegerDatabaseField(name="id"),
        "run_id": IntegerDatabaseField(name="run_id"),
        "run_attempt": IntegerDatabaseField(name="run_attempt"),
        "name": StringDatabaseField(name="name"),
        "workflow_name": StringDatabaseField(name="workflow_name"),
        "head_sha": StringDatabaseField(name="head_sha"),
        "head_branch": StringDatabaseField(name="head_branch"),
        "status": StringDatabaseField(name="status"),
        "conclusion": StringDatabaseField(name="conclusion", nullable=True),
        "labels": StringDatabaseField(name="labels"),
        "runner_name": StringDatabaseField(name="runner_name"),
        "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
        "created_at_raw": StringDatabaseField(
            name="created_at_raw", description="The unparsed ISO-8601 creation time, for a string scan floor."
        ),
        "started_at": DateTimeDatabaseField(name="started_at", nullable=True),
        "completed_at": DateTimeDatabaseField(name="completed_at", nullable=True),
        "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
        "queue_seconds": IntegerDatabaseField(name="queue_seconds", nullable=True),
        "provisioning_seconds": IntegerDatabaseField(name="provisioning_seconds", nullable=True),
        "is_rerun_copy": BooleanDatabaseField(name="is_rerun_copy"),
        "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
        "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
        "native_job_id": StringDatabaseField(name="native_job_id", nullable=True),
        "native_attempt_id": StringDatabaseField(name="native_attempt_id", nullable=True),
        "provider": StringDatabaseField(name="provider", nullable=True),
        "os": StringDatabaseField(name="os", nullable=True),
        "vcpu": IntegerDatabaseField(name="vcpu", nullable=True),
        "multiplier": IntegerDatabaseField(name="multiplier", nullable=True),
        "billable_seconds": IntegerDatabaseField(name="billable_seconds", nullable=True),
        "estimated_cost_usd": FloatDatabaseField(name="estimated_cost_usd", nullable=True),
        **_STORAGE_FIELDS,
    }

    def to_printed_clickhouse(self, context: HogQLContext) -> str:
        return CI_JOBS_TABLE_BASE_NAME

    def to_printed_hogql(self) -> str:
        return CI_JOBS_TABLE_BASE_NAME


def add_stored_ci_tables(database: Database) -> None:
    for table in (EngineeringAnalyticsCIRunsPrecomputedTable(), EngineeringAnalyticsCIJobsPrecomputedTable()):
        name = table.to_printed_hogql()
        database.tables.add_child(TableNode(name=name, table=table))
