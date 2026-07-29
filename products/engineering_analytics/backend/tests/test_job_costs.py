import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

import pandas as pd

from posthog.hogql.query import execute_hogql_query

from products.engineering_analytics.backend.logic.cost import (
    RunnerOS,
    RunnerProvider,
    billing_multiplier,
    classify_runner,
    estimate_job_cost_usd,
)
from products.engineering_analytics.backend.logic.views import job_costs
from products.engineering_analytics.backend.logic.views.source_schema import (
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.job_costs"
GITHUB_SOURCE_PREFIX = "myprefix"

# The classification matrix: (scenario, labels, started_at, completed_at, status). The view derives
# cost from labels + elapsed only, so every row exercises a distinct classify_runner / cost branch.
# Expected values are computed from the Python model in the test, so a row fails only on Python↔SQL
# drift — exactly the regression this guards.
_BASE = "2026-01-01 10:00:00"


def _plus(seconds: int) -> str:
    minute, second = divmod(10 * 3600 + seconds, 60)
    hour, minute = divmod(minute, 60)
    return f"2026-01-01 {hour:02d}:{minute:02d}:{second:02d}"


_MATRIX: list[tuple[str, list[str], str, str | None, str]] = [
    ("depot_linux_sized", ["depot-ubuntu-22.04-16"], _BASE, _plus(600), "completed"),
    ("depot_linux_default", ["depot-ubuntu-latest"], _BASE, _plus(300), "completed"),
    ("depot_macos_versioned", ["depot-macos-14"], _BASE, _plus(600), "completed"),
    ("depot_windows", ["depot-windows-2022"], _BASE, _plus(600), "completed"),
    ("github_hosted", ["ubuntu-latest"], _BASE, _plus(300), "completed"),
    ("unknown_labels", ["self-hosted-custom"], _BASE, _plus(300), "completed"),
    ("decoy_depot_cache", ["depot-docker-cache", "ubuntu-latest"], _BASE, _plus(300), "completed"),
    ("depot_unknown_size", ["depot-ubuntu-22.04-6"], _BASE, _plus(600), "completed"),
    ("unsettled_no_completion", ["depot-ubuntu-latest"], _BASE, None, "in_progress"),
    ("zero_elapsed", ["depot-ubuntu-latest"], _BASE, _BASE, "completed"),
    ("negative_elapsed", ["depot-ubuntu-latest"], _plus(30), _BASE, "completed"),
    ("empty_labels", [], _BASE, _plus(300), "completed"),
]


def _elapsed_seconds(started: str, completed: str | None, status: str) -> int | None:
    # Mirror the jobs builder: duration is only computed for completed jobs, as completed - started.
    if status != "completed" or completed is None:
        return None
    return int((pd.Timestamp(completed) - pd.Timestamp(started)).total_seconds())


def _expected_billable(labels: list[str], elapsed: int | None) -> int | None:
    tier = classify_runner(labels)
    if tier is None or tier.provider is not RunnerProvider.DEPOT or tier.os is not RunnerOS.LINUX or elapsed is None:
        return None
    return max(elapsed, 0)


def _job_row(job_id: int, labels: list[str], started: str, completed: str | None, status: str) -> dict[str, Any]:
    return {
        "id": job_id,
        "run_id": 9000 + job_id,
        "run_attempt": 1,
        "name": f"job-{job_id}",
        "workflow_name": "CI",
        "status": status,
        "conclusion": "success" if status == "completed" else None,
        "head_sha": f"sha{job_id}",
        "head_branch": "main",
        "labels": json.dumps(labels),
        "runner_name": "runner-x",
        "runner_group_name": "",
        "created_at": started,
        "started_at": started,
        "completed_at": completed,
        "steps": "[]",
    }


class TestJobCostsViewParity(ClickhouseTestMixin, BaseTest):
    """The generated view SQL must produce exactly what the Python cost model produces.

    This is the drift guard for the single-source-of-truth contract: the view is rendered from the
    same constants as logic.cost, so any change to one side that isn't matched on the other shows up
    here. Skips when object storage is unreachable so the suite still runs without the dev stack.
    """

    def _create_table(self, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> str:
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
                source_prefix=GITHUB_SOURCE_PREFIX,
            )
        except PermissionError as err:
            self.skipTest(f"object storage unavailable: {err}")
        self.addCleanup(cleanup)
        return table.name

    def test_view_matches_python_cost_model(self) -> None:
        jobs_table = self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(i, labels, started, completed, status)
                for i, (_, labels, started, completed, status) in enumerate(_MATRIX)
            ],
        )
        # A runs table with no matching rows: the cost columns don't depend on the join, so the LEFT
        # JOIN just leaves attribution NULL — exactly the "job without a run row" path.
        runs_table = self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [dict.fromkeys(WORKFLOW_RUNS_COLUMNS)],
        )

        sql = (
            "SELECT job_name, provider, os, vcpu, multiplier, billable_seconds, estimated_cost_usd "
            f"FROM ({job_costs.build_query(jobs_table=jobs_table, runs_table=runs_table)}) ORDER BY job_name"
        )
        rows = execute_hogql_query(query=sql, team=self.team, query_type="engineering_analytics.test").results
        by_job = {row[0]: row for row in rows}

        for index, (scenario, labels, started, completed, status) in enumerate(_MATRIX):
            elapsed = _elapsed_seconds(started, completed, status)
            tier = classify_runner(labels)
            _job_name, provider, os_, vcpu, multiplier, billable, cost = by_job[f"job-{index}"]

            assert provider == (tier.provider.value if tier else None), scenario
            assert os_ == (tier.os.value if tier else None), scenario
            assert vcpu == (tier.vcpu if tier else None), scenario
            assert multiplier == (billing_multiplier(tier) if tier else None), scenario
            assert billable == _expected_billable(labels, elapsed), scenario

            expected_cost = estimate_job_cost_usd(labels, elapsed)
            if expected_cost is None:
                assert cost is None, scenario
            else:
                assert cost == pytest.approx(expected_cost), scenario
