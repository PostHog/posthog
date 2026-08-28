"""GitHub and Trunk source warehouse fixtures shared across this product's test files."""

import os
import json
import zlib
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest

import pandas as pd

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.sources import (
    ISSUE_EVENTS_SCHEMA,
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
    GitHubTables,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.github_fixtures"

# Non-default prefix on purpose: every fixture below lands tables named
# `myprefixgithub_*`, so the resolver and builders are proven against a name the old
# hardcoded `github_*` constants would never have matched.
GITHUB_SOURCE_PREFIX = "myprefix"


@contextmanager
def seeding_object_storage(test: BaseTest) -> Iterator[None]:
    # Skipping locally keeps the suite usable without the dev stack; skipping in CI would drop every
    # warehouse-backed assertion behind a green job, so there it raises.
    try:
        yield
    except PermissionError as err:
        if os.environ.get("CI"):
            raise
        test.skipTest(f"object storage unavailable: {err}")


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


def create_trunk_source(
    team: Team, *, prefix: str = "trunkprefix_", source_id: str = "trunk-source"
) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=source_id,
        connection_id=source_id,
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSourceType.TRUNKIO,
        prefix=prefix,
        job_inputs={},
    )


def _trunk_queue_row(
    entry_id: str,
    state: str,
    pr_number: int,
    state_changed_at: str,
    *,
    skip_the_line: bool = False,
    priority_name: str = "medium",
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "state": state,
        "pr_number": pr_number,
        "priority_name": priority_name,
        "skip_the_line": skip_the_line,
        "state_changed_at": state_changed_at,
    }


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
    team: Team, *, prefix: str = GITHUB_SOURCE_PREFIX, repository: str = "", include_issue_events: bool = False
) -> GitHubTables:
    """A GitHub source with pull_requests/workflow_runs schemas over empty ORM tables.

    The resolver finds these without touching object storage; pair with a mocked query
    when only resolution (not real warehouse data) matters. ``include_issue_events``
    links the optional issue-events schema too, activating the transition reads.
    """
    source = create_github_source(team, prefix=prefix, repository=repository)
    pr_table = create_warehouse_table_row(team, name=f"{prefix}github_pull_requests", source=source)
    run_table = create_warehouse_table_row(team, name=f"{prefix}github_workflow_runs", source=source)
    link_schema(team, source, name=PULL_REQUESTS_SCHEMA, table=pr_table)
    link_schema(team, source, name=WORKFLOW_RUNS_SCHEMA, table=run_table)
    issue_events_table = None
    if include_issue_events:
        events_table = create_warehouse_table_row(team, name=f"{prefix}github_issue_events", source=source)
        link_schema(team, source, name=ISSUE_EVENTS_SCHEMA, table=events_table)
        issue_events_table = events_table.name
    return GitHubTables(
        pull_requests=pr_table.name,
        workflow_runs=run_table.name,
        issue_events=issue_events_table,
        repository=repository,
    )


def repo_id(full_name: str) -> int:
    """A stable synthetic GitHub repo id for a fixture repo — distinct per ``owner/name``."""
    return zlib.crc32(full_name.encode())


def pr_association_entry(number: int, *, base_repo: str = "PostHog/posthog") -> dict[str, Any]:
    """One entry of a run's ``pull_requests`` association, shaped like the real webhook payload.

    ``base.repo.id`` is what the curated builder matches against the run's own ``repository.id`` to
    ignore the fork network's PRs. Pass ``base_repo`` to forge an entry based in a *different* repo —
    that's what a default-branch push really lands, and the builder must skip it.
    """
    return {"number": number, "base": {"repo": {"id": repo_id(base_repo)}}}


def pr_association(*numbers: int, base_repo: str = "PostHog/posthog") -> str:
    """A run's ``pull_requests`` association over one base repo, serialized as the column lands it."""
    return json.dumps([pr_association_entry(number, base_repo=base_repo) for number in numbers])


def _user(login: str) -> str:
    return f'{{"login": "{login}", "avatar_url": "https://avatars/{login}"}}'


def _base(full_name: str, ref: str = "", default_branch: str = "") -> str:
    # Mirrors the real payload: base.repo is a full repository object, so it carries default_branch.
    repo = f'{{"full_name": "{full_name}", "default_branch": "{default_branch}"}}'
    return f'{{"ref": "{ref}", "repo": {repo}}}'


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
    merge_commit_sha: str | None = None,
    head_sha: str = "",
    head_ref: str = "",
    base_ref: str = "",
    full_name: str = "PostHog/posthog",
    default_branch: str = "",
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
        "merge_commit_sha": merge_commit_sha,
        "user": _user(login),
        "head": f'{{"sha": "{head_sha}", "ref": "{head_ref}"}}',
        "base": _base(full_name, base_ref, default_branch),
        "labels": _labels(*labels),
    }


def _issue_event_row(
    event_id: int,
    event: str,
    pr_number: int,
    created_at: str,
    *,
    login: str = "alice",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "event": event,
        "actor": _user(login),
        "issue": f'{{"number": {pr_number}}}',
        "created_at": created_at,
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
    commit_message: str | None = None,
    actor: str = "alice",
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
        "pull_requests": pr_association(pr_number, base_repo=full_name) if pr_number is not None else None,
        "repository": json.dumps({"full_name": full_name, "id": repo_id(full_name)}),
        "head_commit": json.dumps({"message": commit_message}) if commit_message is not None else None,
        "actor": json.dumps({"login": actor}),
    }


def create_github_warehouse_table(test: BaseTest, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> str:
    # Returns the real table name (prefixed), which the builder is then told to read,
    # proving build_query honors the resolved name instead of a hardcoded one.
    df = pd.DataFrame(rows, columns=list(columns.keys()))
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    df.to_csv(tmp.name, index=False)
    tmp.close()
    test.addCleanup(Path(tmp.name).unlink, missing_ok=True)
    with seeding_object_storage(test):
        table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
            csv_path=Path(tmp.name),
            table_name=base_name,
            table_columns=columns,
            test_bucket=TEST_BUCKET,
            team=test.team,
            source_prefix=GITHUB_SOURCE_PREFIX,
        )
    test.addCleanup(cleanup)
    return table.name
