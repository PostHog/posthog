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
    billed_elapsed_seconds,
    billing_multiplier,
    classify_runner,
    estimate_job_cost_usd,
)
from products.engineering_analytics.backend.logic.views import depot_ci, job_costs
from products.engineering_analytics.backend.logic.views.source_schema import (
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    pr_association_entry,
    repo_id,
    seeding_object_storage,
)
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.job_costs"
GITHUB_SOURCE_PREFIX = "myprefix"

# Each row is (scenario, labels, started_at, completed_at, status) and exercises a distinct
# classify_runner or cost branch. No row carries a steps payload, so billed elapsed equals wall-clock.
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
    # Mirrors the jobs builder, which computes a duration only for completed jobs.
    if status != "completed" or completed is None:
        return None
    return int((pd.Timestamp(completed) - pd.Timestamp(started)).total_seconds())


def _expected_billable(labels: list[str], elapsed: float | None) -> float | None:
    tier = classify_runner(labels)
    if tier is None or tier.provider is not RunnerProvider.DEPOT or tier.os is not RunnerOS.LINUX or elapsed is None:
        return None
    return max(elapsed, 0)


def _job_row(
    job_id: int,
    labels: list[str],
    started: str | None,
    completed: str | None,
    status: str,
    *,
    run_id: int | None = None,
    run_attempt: int = 1,
    name: str | None = None,
    steps: str = "[]",
) -> dict[str, Any]:
    return {
        "id": job_id,
        "run_id": run_id if run_id is not None else 9000 + job_id,
        "run_attempt": run_attempt,
        "name": name if name is not None else f"job-{job_id}",
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
        "steps": steps,
    }


_REPO = "PostHog/posthog"


def _run_row(run_id: int, *, run_attempt: int, pr_number: int) -> dict[str, Any]:
    return dict.fromkeys(WORKFLOW_RUNS_COLUMNS) | {
        "id": run_id,
        "name": "CI",
        "head_sha": "sha-head",
        "head_branch": "feature-branch",
        "status": "completed",
        "conclusion": "failure",
        "created_at": _BASE,
        "run_started_at": _BASE,
        "updated_at": _plus(1000),
        "run_attempt": run_attempt,
        "pull_requests": json.dumps([pr_association_entry(pr_number, base_repo=_REPO)]),
        "repository": json.dumps({"full_name": _REPO, "id": repo_id(_REPO)}),
    }


def _cost_query(jobs_table: str, runs_table: str) -> str:
    return job_costs.build_query(
        jobs_table=depot_ci.with_depot_jobs(jobs_table, None, runs_table),
        runs_table=depot_ci.with_depot_runs(runs_table, None, None, None),
    )


class TestJobCostsViewParity(ClickhouseTestMixin, BaseTest):
    def _create_table(self, base_name: str, columns: dict, rows: list[dict[str, Any]]) -> str:
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
                source_prefix=GITHUB_SOURCE_PREFIX,
            )
        self.addCleanup(cleanup)
        return table.name

    def test_builder_columns_match_the_field_contract(self) -> None:
        jobs_table = self._create_table("github_workflow_jobs", WORKFLOW_JOBS_COLUMNS, [_job_row(0, *_MATRIX[0][1:])])
        runs_table = self._create_table(
            "github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [dict.fromkeys(WORKFLOW_RUNS_COLUMNS)]
        )
        query = _cost_query(jobs_table, runs_table)
        columns = execute_hogql_query(
            query=f"SELECT * FROM ({query})", team=self.team, query_type="engineering_analytics.test"
        ).columns
        assert columns == list(job_costs.BUILDER_FIELDS)

    def test_view_matches_python_cost_model(self) -> None:
        jobs_table = self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(i, labels, started, completed, status)
                for i, (_, labels, started, completed, status) in enumerate(_MATRIX)
            ],
        )
        # No run row matches, so this also covers a job whose run row is missing.
        runs_table = self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [dict.fromkeys(WORKFLOW_RUNS_COLUMNS)],
        )

        sql = (
            "SELECT job_name, provider, os, vcpu, multiplier, billable_seconds, estimated_cost_usd "
            f"FROM ({_cost_query(jobs_table, runs_table)}) ORDER BY job_name"
        )
        rows = execute_hogql_query(query=sql, team=self.team, query_type="engineering_analytics.test").results
        by_job = {row[0]: row for row in rows}

        for index, (scenario, labels, started, completed, status) in enumerate(_MATRIX):
            billed = billed_elapsed_seconds(_elapsed_seconds(started, completed, status), None)
            tier = classify_runner(labels)
            _job_name, provider, os_, vcpu, multiplier, billable, cost = by_job[f"job-{index}"]

            assert provider == (tier.provider.value if tier else None), scenario
            assert os_ == (tier.os.value if tier else None), scenario
            assert vcpu == (tier.vcpu if tier else None), scenario
            assert multiplier == (billing_multiplier(tier) if tier else None), scenario
            assert billable == _expected_billable(labels, billed), scenario

            expected_cost = estimate_job_cost_usd(labels, billed)
            if expected_cost is None:
                assert cost is None, scenario
            else:
                assert cost == pytest.approx(expected_cost), scenario

    def test_cost_is_billed_from_the_first_step_not_from_started_at(self) -> None:
        # GitHub stamps started_at when Depot accepts the job, but Depot bills from the first step.
        labels = ["depot-ubuntu-latest"]
        steps = json.dumps(
            [
                {"name": "Set up job", "started_at": _plus(23), "completed_at": _plus(30)},
                {"name": "Run tests", "started_at": _plus(30), "completed_at": _plus(600)},
            ]
        )
        jobs_table = self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(1, labels, _BASE, _plus(600), "completed", name="with-steps", steps=steps),
                _job_row(2, labels, _BASE, _plus(600), "completed", name="no-steps"),
            ],
        )
        runs_table = self._create_table(
            "github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [dict.fromkeys(WORKFLOW_RUNS_COLUMNS)]
        )

        sql = (
            "SELECT job_name, duration_seconds, billable_seconds, estimated_cost_usd "
            f"FROM ({_cost_query(jobs_table, runs_table)}) ORDER BY job_name"
        )
        rows = execute_hogql_query(query=sql, team=self.team, query_type="engineering_analytics.test").results
        by_job = {row[0]: row for row in rows}

        _name, duration, billable, cost = by_job["with-steps"]
        assert duration == 600
        assert billable == billed_elapsed_seconds(600, 23) == 577
        assert cost == pytest.approx(estimate_job_cost_usd(labels, 577))

        _name, duration, billable, cost = by_job["no-steps"]
        assert duration == 600
        assert billable == billed_elapsed_seconds(600, None) == 600
        assert cost == pytest.approx(estimate_job_cost_usd(labels, 600))

    def test_earlier_attempt_jobs_keep_their_run_attribution(self) -> None:
        # The runs snapshot upserts by id, so after a partial re-run only the attempt-2 run row exists.
        # A join on (run_id, run_attempt) leaves the attempt-1 jobs, which are the ones that executed,
        # without a repo or PR.
        labels = ["depot-ubuntu-latest"]
        run_id, pr_number = 8800, 42
        jobs_table = self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(1, labels, _BASE, _plus(600), "completed", run_id=run_id, run_attempt=1, name="passed"),
                _job_row(2, labels, _BASE, _plus(300), "completed", run_id=run_id, run_attempt=1, name="failed"),
                # Attempt 2 lists the passed job again with attempt 1's timestamps and re-runs the failed one.
                _job_row(3, labels, _BASE, _plus(600), "completed", run_id=run_id, run_attempt=2, name="passed"),
                _job_row(4, labels, _plus(700), _plus(1000), "completed", run_id=run_id, run_attempt=2, name="failed"),
            ],
        )
        runs_table = self._create_table(
            "github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [_run_row(run_id, run_attempt=2, pr_number=pr_number)]
        )

        sql = (
            "SELECT job_name, run_attempt, repo_owner, repo_name, pr_number, is_rerun_copy, estimated_cost_usd "
            f"FROM ({_cost_query(jobs_table, runs_table)}) "
            "ORDER BY job_name, run_attempt"
        )
        rows = execute_hogql_query(query=sql, team=self.team, query_type="engineering_analytics.test").results
        by_attempt = {(row[0], row[1]): row for row in rows}

        for row in rows:
            assert (row[2], row[3], row[4]) == ("PostHog", "posthog", pr_number), row[0]

        assert not by_attempt[("passed", 1)][5]
        assert by_attempt[("passed", 1)][6] == pytest.approx(estimate_job_cost_usd(labels, 600))
        assert by_attempt[("passed", 2)][5]
        assert by_attempt[("passed", 2)][6] is None

        # Three executions happened: the passed job once and the failed job twice.
        passed_cost = estimate_job_cost_usd(labels, 600)
        failed_cost = estimate_job_cost_usd(labels, 300)
        assert passed_cost is not None and failed_cost is not None
        total = sum(row[6] for row in rows if row[6] is not None)
        assert total == pytest.approx(passed_cost + 2 * failed_cost)

    def test_rerun_copies_are_flagged_and_not_costed(self) -> None:
        # After "Re-run failed jobs", GitHub lists the passed job again under attempt 2 with a new id
        # and attempt 1's timestamps, although it did not run again. The two queued rows share NULL
        # timestamps, which group together as a duplicate key, and they must not read as copies.
        labels = ["depot-ubuntu-latest"]
        run_id = 7700
        jobs_table = self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(1, labels, _BASE, _plus(600), "completed", run_id=run_id, run_attempt=1, name="passed"),
                _job_row(2, labels, _BASE, _plus(300), "completed", run_id=run_id, run_attempt=1, name="failed"),
                _job_row(3, labels, _BASE, _plus(600), "completed", run_id=run_id, run_attempt=2, name="passed"),
                _job_row(4, labels, _plus(700), _plus(1000), "completed", run_id=run_id, run_attempt=2, name="failed"),
                _job_row(5, labels, None, None, "queued", run_id=run_id, run_attempt=1, name="queued"),
                _job_row(6, labels, None, None, "queued", run_id=run_id, run_attempt=2, name="queued"),
            ],
        )
        runs_table = self._create_table(
            "github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [dict.fromkeys(WORKFLOW_RUNS_COLUMNS)]
        )

        sql = (
            "SELECT job_name, run_attempt, is_rerun_copy, duration_seconds, billable_seconds, estimated_cost_usd "
            f"FROM ({_cost_query(jobs_table, runs_table)}) "
            "ORDER BY job_name, run_attempt"
        )
        rows = execute_hogql_query(query=sql, team=self.team, query_type="engineering_analytics.test").results
        by_attempt = {(row[0], row[1]): row for row in rows}

        # A copy is flagged and stays a row.
        assert len(rows) == 6

        _n, _a, copy, duration, billable, cost = by_attempt[("passed", 2)]
        assert copy
        assert duration == 600
        assert billable is None
        assert cost is None

        for key in (("passed", 1), ("failed", 1), ("failed", 2)):
            _n, _a, copy, _duration, billable, cost = by_attempt[key]
            assert not copy, key
            assert billable == _expected_billable(labels, 600 if key == ("passed", 1) else 300), key
            assert cost == pytest.approx(estimate_job_cost_usd(labels, billable)), key

        for key in (("queued", 1), ("queued", 2)):
            _n, _a, copy, duration, billable, cost = by_attempt[key]
            assert not copy, key
            # An unsettled job has a NULL cost and never a zero cost.
            assert duration is None and billable is None and cost is None, key
