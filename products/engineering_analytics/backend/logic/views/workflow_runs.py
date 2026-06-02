"""The ``engineering_analytics_workflow_runs`` curated read layer.

A per-team HogQL view over the raw ``github_workflow_runs`` warehouse snapshot.
It exposes the CI run columns honestly: ``status`` and ``conclusion`` are passed
through unchanged (a conclusion can be stale until the ``workflow_run`` webhook
settles it — see SPEC §9), and ``duration_seconds`` is only computed for
completed runs. ``head_sha`` is the canonical join key back to
``engineering_analytics_pull_requests`` for a PR's CI status.
"""

from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    SavedQuery,
    StringDatabaseField,
)

VIEW_NAME = "engineering_analytics_workflow_runs"
SOURCE_TABLE = "github_workflow_runs"

FIELDS: dict[str, FieldOrTable] = {
    "id": IntegerDatabaseField(name="id"),
    "workflow_name": StringDatabaseField(name="workflow_name"),
    "head_sha": StringDatabaseField(name="head_sha"),
    "status": StringDatabaseField(name="status"),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "run_started_at": DateTimeDatabaseField(name="run_started_at"),
    "updated_at": DateTimeDatabaseField(name="updated_at"),
    "created_at": DateTimeDatabaseField(name="created_at"),
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "repo_owner": StringDatabaseField(name="repo_owner"),
    "repo_name": StringDatabaseField(name="repo_name"),
}


def build_query() -> str:
    repo_full_name = "JSONExtractString(repository, 'full_name')"
    return f"""
        SELECT
            id,
            name AS workflow_name,
            head_sha,
            status,
            conclusion,
            run_started_at,
            updated_at,
            created_at,
            if(status = 'completed', dateDiff('second', run_started_at, updated_at), NULL) AS duration_seconds,
            arrayElement(splitByChar('/', {repo_full_name}), 1) AS repo_owner,
            arrayElement(splitByChar('/', {repo_full_name}), 2) AS repo_name
        FROM {SOURCE_TABLE}
    """


def build_view() -> SavedQuery:
    return SavedQuery(id=VIEW_NAME, name=VIEW_NAME, query=build_query(), fields=FIELDS)
