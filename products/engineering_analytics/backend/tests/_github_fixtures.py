"""GitHub source and warehouse-table fixtures shared across this product's test files."""

import tempfile
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest

import pandas as pd

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    GitHubTables,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.github_fixtures"

# Non-default prefix on purpose: every fixture below lands tables named
# `myprefixgithub_*`, so the resolver and builders are proven against a name the old
# hardcoded `github_*` constants would never have matched.
GITHUB_SOURCE_PREFIX = "myprefix"


def create_github_source(
    team: Team, *, prefix: str = GITHUB_SOURCE_PREFIX, source_id: str = "gh-source", repository: str = ""
) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=source_id,
        connection_id=source_id,
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSourceType.GITHUB,
        prefix=prefix,
        job_inputs={"repository": repository} if repository else {},
    )


def link_schema(
    team: Team,
    source: ExternalDataSource,
    *,
    name: str,
    table: DataWarehouseTable | None,
    should_sync: bool = True,
) -> ExternalDataSchema:
    return ExternalDataSchema.objects.create(team=team, source=source, name=name, table=table, should_sync=should_sync)


def create_warehouse_table_row(
    team: Team, *, name: str, source: ExternalDataSource | None = None
) -> DataWarehouseTable:
    # ORM-only table (no object storage); for resolver/mapping tests that mock the query.
    return DataWarehouseTable.objects.create(
        team=team,
        name=name,
        format=DataWarehouseTable.TableFormat.CSVWithNames,
        url_pattern="",
        external_data_source=source,
        columns={},
    )


def connect_github_source_without_data(
    team: Team, *, prefix: str = GITHUB_SOURCE_PREFIX, repository: str = ""
) -> GitHubTables:
    """A GitHub source with pull_requests/workflow_runs schemas over empty ORM tables.

    The resolver finds these without touching object storage; pair with a mocked query
    when only resolution (not real warehouse data) matters.
    """
    source = create_github_source(team, prefix=prefix, repository=repository)
    pr_table = create_warehouse_table_row(team, name=f"{prefix}github_pull_requests", source=source)
    run_table = create_warehouse_table_row(team, name=f"{prefix}github_workflow_runs", source=source)
    link_schema(team, source, name=PULL_REQUESTS_SCHEMA, table=pr_table)
    link_schema(team, source, name=WORKFLOW_RUNS_SCHEMA, table=run_table)
    return GitHubTables(pull_requests=pr_table.name, workflow_runs=run_table.name, repository=repository)


def _user(login: str) -> str:
    return f'{{"login": "{login}", "avatar_url": "https://avatars/{login}"}}'


def _base(full_name: str, ref: str = "") -> str:
    return f'{{"ref": "{ref}", "repo": {{"full_name": "{full_name}"}}}}'


def _labels(*names: str) -> str:
    return "[" + ", ".join(f'{{"name": "{name}"}}' for name in names) + "]"


def _pr_row(
    number: int,
    login: str,
    state: str,
    draft: int,
    created_at: str,
    *,
    merged_at: str | None = None,
    head_sha: str = "",
    head_ref: str = "",
    base_ref: str = "",
    full_name: str = "PostHog/posthog",
    labels: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": 1000 + number,
        "number": number,
        "title": f"PR {number}",
        "state": state,
        "draft": draft,
        "created_at": created_at,
        "updated_at": merged_at or created_at,
        "merged_at": merged_at,
        "closed_at": merged_at,
        "user": _user(login),
        "head": f'{{"sha": "{head_sha}", "ref": "{head_ref}"}}',
        "base": _base(full_name, base_ref),
        "labels": _labels(*labels),
    }


def _run_row(
    run_id: int,
    name: str,
    head_sha: str,
    status: str,
    conclusion: str | None,
    run_started_at: str,
    updated_at: str,
    *,
    full_name: str = "PostHog/posthog",
    run_attempt: int = 1,
    pr_number: int | None = None,
    head_branch: str = "main",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": name,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "status": status,
        "conclusion": conclusion,
        "created_at": run_started_at,
        "run_started_at": run_started_at,
        "updated_at": updated_at,
        "run_attempt": run_attempt,
        # Mirror the real Nullable(String) column: an unassociated run lands NULL, not "[]",
        # so the builder's ifNull(pull_requests, '[]') guard is exercised on the real path.
        "pull_requests": f'[{{"number": {pr_number}}}]' if pr_number is not None else None,
        "repository": f'{{"full_name": "{full_name}"}}',
    }


def create_github_warehouse_table(test: BaseTest, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> str:
    # Returns the real table name (prefixed), which the builder is then told to read,
    # proving build_query honors the resolved name instead of a hardcoded one. Skips the
    # calling test when object storage is unreachable so the suite runs without the dev stack.
    df = pd.DataFrame(rows, columns=list(columns.keys()))
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    df.to_csv(tmp.name, index=False)
    tmp.close()
    test.addCleanup(Path(tmp.name).unlink, missing_ok=True)
    try:
        table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
            csv_path=Path(tmp.name),
            table_name=base_name,
            table_columns=columns,
            test_bucket=TEST_BUCKET,
            team=test.team,
            source_prefix=GITHUB_SOURCE_PREFIX,
        )
    except PermissionError as err:
        test.skipTest(f"object storage unavailable: {err}")
    test.addCleanup(cleanup)
    return table.name
