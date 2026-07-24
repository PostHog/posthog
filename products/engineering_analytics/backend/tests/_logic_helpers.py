"""Shared fixtures and warehouse seeding for the test_logic_* domain files."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.utils import timezone

import pandas as pd

from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    GITHUB_SOURCE_PREFIX,
    _pr_row,
    _run_row,
    create_github_source,
    link_schema,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

# Every query module runs HogQL through this method; patch it to test row mapping without a
# warehouse. Patching the unbound method means the mock is called without `self`, so a plain
# return_value / side_effect works as before.
_RUN_QUERY = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.run"
_PR_LIST = "products.engineering_analytics.backend.logic.queries.pull_request_list"

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.logic"


def _resp(results: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(results=results)


def _pr_list_run(rows: list[tuple], push_rows: list[tuple] | None = None):
    """Mocked ``curated.run`` for the PR-list path, which now issues two queries: the list
    query returns ``rows``; the scoped push-history query returns ``push_rows``."""

    def run(sql: str, *, query_type: str, **kwargs) -> SimpleNamespace:
        if query_type == "engineering_analytics.pr_push_history":
            return _resp(push_rows or [])
        return _resp(rows)

    return run


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _ago(days: int) -> str:
    return _ago_with_duration(days, 0)[0]


def _ago_with_duration(days: int, duration_seconds: int) -> tuple[str, str]:
    # Seed dates relative to real time: HogQL now() runs server-side and ignores
    # freezegun, so window/age assertions must share the clock the query uses.
    started_at = timezone.now() - timedelta(days=days)
    updated_at = started_at + timedelta(seconds=duration_seconds)
    fmt = "%Y-%m-%d %H:%M:%S"
    return started_at.strftime(fmt), updated_at.strftime(fmt)


def _job_row(
    job_id: int,
    run_id: int,
    name: str,
    conclusion: str,
    *,
    run_attempt: int = 1,
    labels: str = '["depot-ubuntu-22.04-4"]',
    started: str = "2026-01-01 00:00:00",
    completed: str = "2026-01-01 00:02:00",
) -> dict[str, Any]:
    return {
        "id": job_id,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "name": name,
        "workflow_name": "CI",
        "status": "completed",
        "conclusion": conclusion,
        "head_sha": "sha60",
        "head_branch": "main",
        "labels": labels,
        "runner_name": "runner-1",
        "runner_group_name": "depot",
        "created_at": started,
        "started_at": started,
        "completed_at": completed,
        "steps": "[]",
    }


def _header(
    state: str,
    *,
    merged_at: datetime | None,
    closed_at: datetime | None = None,
    is_bot: bool = False,
    head_sha: str = "sha10",
) -> tuple:
    # Mirrors the SELECT column order in query_pr_lifecycle's header query.
    return (
        1010,
        10,
        "PR 10",
        state,
        False,
        _dt("2026-01-10T09:00:00"),
        merged_at,
        closed_at if closed_at is not None else merged_at,
        "alice",
        "https://avatars/alice",
        is_bot,
        "PostHog",
        "posthog",
        head_sha,
    )


class _WarehouseMixin(ClickhouseTestMixin, BaseTest):
    """Seeds warehouse tables behind a connected GitHub source with a non-default prefix,
    so the full resolve -> build -> query path runs end to end against `myprefixgithub_*`
    tables. Skips when object storage is unreachable so the suite still runs without the
    dev stack."""

    def setUp(self) -> None:
        super().setUp()
        self._github_source: ExternalDataSource | None = None

    def _create_table(
        self,
        base_name: str,
        columns: dict,
        rows: list[dict[str, Any]],
        *,
        source: ExternalDataSource | None = None,
        prefix: str = GITHUB_SOURCE_PREFIX,
    ) -> None:
        # Defaults to the mixin's single shared source; pass source + prefix to seed a second
        # source (e.g. one GitHub source per repository) under a distinct table prefix.
        if source is None:
            if self._github_source is None:
                self._github_source = create_github_source(self.team)
            source = self._github_source
        df = pd.DataFrame(rows, columns=list(columns.keys()))
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        df.to_csv(tmp.name, index=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        try:
            table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
                csv_path=Path(tmp.name),
                table_name=base_name,
                table_columns=columns,
                test_bucket=TEST_BUCKET,
                team=self.team,
                source=source,
                source_prefix=prefix,
            )
        except PermissionError as err:
            self.skipTest(f"object storage unavailable: {err}")
        self.addCleanup(cleanup)
        # base_name is "github_<endpoint>"; the synced schema/endpoint is its suffix.
        link_schema(self.team, source, name=base_name.removeprefix("github_"), table=table)


class _EndpointsWarehouseMixin(_WarehouseMixin):
    """End-to-end aggregates over real warehouse tables. Seeds dates relative to
    real time (HogQL now() is server-side). Skips when object storage is
    unreachable."""

    def _seed(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                # open, recent (<7d), human, failing CI on sha10
                _pr_row(10, "alice", "open", 0, _ago(1), head_sha="sha10", labels=("bug",)),
                # open, old (>7d), human -> stuck; passing CI on sha11
                _pr_row(11, "bob", "open", 0, _ago(30), head_sha="sha11"),
                # open draft -> not stuck
                _pr_row(12, "carol", "open", 1, _ago(30), head_sha="sha12"),
                # open bot -> not stuck
                _pr_row(13, "dependabot[bot]", "open", 0, _ago(30), head_sha="sha13"),
                # open allowlisted bot (no [bot] suffix) -> is_bot, not stuck
                _pr_row(16, "renovate", "open", 0, _ago(30), head_sha="sha16"),
                # merged within the default 30d window -> in the list, not open
                _pr_row(14, "alice", "closed", 0, _ago(40), merged_at=_ago(5), head_sha="sha14"),
                # merged long ago -> outside the window, excluded from the list
                _pr_row(15, "alice", "closed", 0, _ago(120), merged_at=_ago(60), head_sha="sha15"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(2001, "CI", "sha10", "completed", "failure", _ago(1), _ago(1), pr_number=10),
                _run_row(2002, "CI", "sha11", "completed", "success", _ago(2), _ago(2), pr_number=11),
                # A second push on PR 10 (new head SHA) that was re-run -> pushes=2, rerun_cycles=1.
                # A non-CI workflow so the CI workflow-health assertions stay at 2 runs.
                _run_row(
                    2003, "Deploy", "sha10b", "completed", "success", _ago(1), _ago(1), pr_number=10, run_attempt=2
                ),
            ],
        )
