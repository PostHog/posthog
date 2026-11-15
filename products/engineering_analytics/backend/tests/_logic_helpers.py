"""Shared fixtures and warehouse seeding for the test_logic_* domain files."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.core.cache import cache
from django.utils import timezone

import pandas as pd

from products.engineering_analytics.backend.logic.sources import DEPOT_JOB_ATTEMPTS_SCHEMA
from products.engineering_analytics.backend.logic.views.source_schema import (
    DEPOT_JOB_ATTEMPTS_COLUMNS,
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    GITHUB_SOURCE_PREFIX,
    _pr_row,
    _run_row,
    create_depot_source,
    create_github_source,
    link_schema,
    seeding_object_storage,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv

# Every query module runs HogQL through this method. A patch of the unbound method is called
# without `self`.
_RUN_QUERY = "products.engineering_analytics.backend.logic.queries._curated.CuratedGitHubSource.run"
_PR_LIST = "products.engineering_analytics.backend.logic.queries.pull_request_list"

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.logic"


def _resp(results: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(results=results)


def _pr_list_run(rows: list[tuple], push_rows: list[tuple] | None = None):
    """Mock ``curated.run`` for the PR-list path, which issues a list query and a push-history query."""

    def run(sql: str, *, query_type: str, **kwargs) -> SimpleNamespace:
        if query_type == "engineering_analytics.pr_push_history":
            return _resp(push_rows or [])
        return _resp(rows)

    return run


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


_seed_clock: datetime | None = None


def anchor_seed_clock() -> None:
    """Pin the clock that every seed in one test reads.

    Seeds format to whole seconds, so two clock samples that straddle a second would put seeded
    rows one second further apart than the test asked for.
    """
    global _seed_clock
    _seed_clock = timezone.now()


def _seed_now() -> datetime:
    return _seed_clock if _seed_clock is not None else timezone.now()


def _ago(days: int) -> str:
    return _ago_with_duration(days, 0)[0]


def _ago_with_duration(days: int, duration_seconds: int) -> tuple[str, str]:
    # HogQL now() runs on the server and ignores a frozen clock, so seed dates are relative to real time.
    started_at = _seed_now() - timedelta(days=days)
    updated_at = started_at + timedelta(seconds=duration_seconds)
    fmt = "%Y-%m-%d %H:%M:%S"
    return started_at.strftime(fmt), updated_at.strftime(fmt)


def _ago_offset_with_duration(days: int, offset_seconds: int, duration_seconds: int) -> tuple[str, str]:
    started_at = _seed_now() - timedelta(days=days) + timedelta(seconds=offset_seconds)
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
    started: str | None = None,
    completed: str | None = None,
    head_branch: str = "main",
    head_sha: str = "sha60",
    steps: str = "[]",
) -> dict[str, Any]:
    # The cost queries floor the jobs scan near the run's start, so a job must be created near its
    # run and not on a fixed calendar date. The cost assertions expect the 2-minute duration.
    default_started, default_completed = _ago_with_duration(1, 120)
    started = started if started is not None else default_started
    completed = completed if completed is not None else default_completed
    return {
        "id": job_id,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "name": name,
        "workflow_name": "CI",
        "status": "completed",
        "conclusion": conclusion,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "labels": labels,
        "runner_name": "runner-1",
        "runner_group_name": "depot",
        "created_at": started,
        "started_at": started,
        "completed_at": completed,
        "steps": steps,
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
    """Seed warehouse tables behind a GitHub source with a non-default prefix, so table resolution is exercised."""

    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self._github_source: ExternalDataSource | None = None

    def _create_table(
        self,
        base_name: str,
        columns: dict,
        rows: list[dict[str, Any]],
        *,
        source: ExternalDataSource | None = None,
        prefix: str = GITHUB_SOURCE_PREFIX,
        schema_name: str | None = None,
    ) -> None:
        if source is None:
            if self._github_source is None:
                self._github_source = create_github_source(self.team)
            source = self._github_source
        df = pd.DataFrame(rows, columns=list(columns.keys()))
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        df.to_csv(tmp.name, index=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        with seeding_object_storage(self):
            table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
                csv_path=Path(tmp.name),
                table_name=base_name,
                table_columns=columns,
                test_bucket=TEST_BUCKET,
                team=self.team,
                source=source,
                source_prefix=prefix,
            )
        self.addCleanup(cleanup)
        # A GitHub schema name is the base name without its "github_" prefix. Other sources pass schema_name.
        link_schema(self.team, source, name=schema_name or base_name.removeprefix("github_"), table=table)

    def _create_depot_table(self, rows: list[dict[str, Any]]) -> None:
        # A Depot source joins the GitHub source that syncs the same repository.
        if self._github_source is None:
            self._github_source = create_github_source(self.team, repository="PostHog/posthog")
        depot = create_depot_source(self.team, prefix="ci", repository="PostHog/posthog")
        self._create_table(
            "depot_job_attempts",
            DEPOT_JOB_ATTEMPTS_COLUMNS,
            rows,
            source=depot,
            prefix="ci",
            schema_name=DEPOT_JOB_ATTEMPTS_SCHEMA,
        )


class _EndpointsWarehouseMixin(_WarehouseMixin):
    def _seed(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(10, "alice", "open", 0, _ago(1), head_sha="sha10", labels=("bug",)),
                # Stuck: open for more than 7 days, by a human, not a draft.
                _pr_row(11, "bob", "open", 0, _ago(30), head_sha="sha11"),
                _pr_row(12, "carol", "open", 1, _ago(30), head_sha="sha12"),
                _pr_row(13, "dependabot[bot]", "open", 0, _ago(30), head_sha="sha13"),
                # A bot from the allowlist, without the [bot] suffix.
                _pr_row(16, "renovate", "open", 0, _ago(30), head_sha="sha16"),
                _pr_row(14, "alice", "closed", 0, _ago(40), merged_at=_ago(5), head_sha="sha14"),
                # Merged before the default 30-day window.
                _pr_row(15, "alice", "closed", 0, _ago(120), merged_at=_ago(60), head_sha="sha15"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(2001, "CI", "sha10", "completed", "failure", _ago(1), _ago(1), pr_number=10),
                _run_row(2002, "CI", "sha11", "completed", "success", _ago(2), _ago(2), pr_number=11),
                # A second, re-run push on PR 10. It uses a non-CI workflow so that the CI workflow
                # counts stay at 2 runs, and starts a minute before sha10 so that a push-history
                # cap of 1 drops it.
                _run_row(
                    2003,
                    "Deploy",
                    "sha10b",
                    "completed",
                    "success",
                    *_ago_offset_with_duration(1, -60, 0),
                    pr_number=10,
                    run_attempt=2,
                ),
                # A merge-queue gate run for PR 10. The queue made its head SHA, so it is not a push.
                _run_row(
                    2004,
                    "Deploy",
                    "sha10queue",
                    "completed",
                    "success",
                    _ago(1),
                    _ago(1),
                    pr_number=9001,
                    head_branch="trunk-merge/pr-10/cabec75e-5181-4429-aea5-0501a52d0688",
                    actor="trunk-io[bot]",
                ),
            ],
        )
