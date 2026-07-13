import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

import pandas as pd

from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.signals.contracts import (
    SOURCE_PRODUCT,
    SOURCE_TYPE_BROKEN_MASTER,
    SOURCE_TYPE_DURATION_REGRESSION,
    SOURCE_TYPE_FLAKY_CHECK,
)
from products.engineering_analytics.backend.logic.signals.detectors import (
    detect_broken_master,
    detect_ci_duration_regressions,
    detect_flaky_checks,
)
from products.engineering_analytics.backend.logic.sources import GitHubTables
from products.engineering_analytics.backend.logic.views.source_schema import (
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP
from products.signals.backend.models import SignalSourceConfig
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.products.engineering_analytics.signals"
GITHUB_SOURCE_PREFIX = "myprefix"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _run_row(
    run_id: int,
    name: str,
    head_sha: str,
    conclusion: str | None,
    started: datetime,
    duration_seconds: int,
    *,
    run_attempt: int = 1,
    head_branch: str = "main",
    status: str = "completed",
    default_branch: str = "main",
) -> dict[str, Any]:
    started_s = _ts(started)
    return {
        "id": run_id,
        "name": name,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "status": status,
        "conclusion": conclusion,
        "created_at": started_s,
        "run_started_at": started_s,
        "updated_at": _ts(started + timedelta(seconds=duration_seconds)),
        "run_attempt": run_attempt,
        "pull_requests": None,
        "repository": json.dumps({"full_name": "PostHog/posthog", "default_branch": default_branch}),
    }


def _job_row(
    job_id: int,
    run_id: int,
    name: str,
    head_sha: str,
    conclusion: str,
    started: datetime,
    *,
    run_attempt: int,
) -> dict[str, Any]:
    started_s = _ts(started)
    return {
        "id": job_id,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "name": name,
        "workflow_name": "CI",
        "status": "completed",
        "conclusion": conclusion,
        "head_sha": head_sha,
        "head_branch": "main",
        "labels": "[]",
        "runner_name": "runner",
        "runner_group_name": "default",
        "created_at": started_s,
        "started_at": started_s,
        "completed_at": _ts(started + timedelta(seconds=60)),
        "steps": "[]",
    }


def test_source_type_constants_match_signals_taxonomy() -> None:
    # Guards the constants ↔ signals taxonomy mirror: a drift here makes emit_signal reject
    # every CI signal as an unknown source_product/source_type, silently emitting nothing.
    assert SOURCE_PRODUCT in {product.value for product in SignalSourceConfig.SourceProduct}
    for source_type in (SOURCE_TYPE_FLAKY_CHECK, SOURCE_TYPE_BROKEN_MASTER, SOURCE_TYPE_DURATION_REGRESSION):
        assert source_type in {choice.value for choice in SignalSourceConfig.SourceType}
        assert (SOURCE_PRODUCT, source_type) in SIGNAL_VARIANT_LOOKUP


class TestCISignalDetectors(ClickhouseTestMixin, BaseTest):
    """Detectors run over a real seeded github_workflow_runs warehouse table. Each test seeds both a
    should-fire and a should-not-fire workflow and asserts the detected set, so it catches both
    missed conditions and false positives. Skips when object storage is unreachable (no dev stack)."""

    def _curated_over_runs(
        self, rows: list[dict[str, Any]], job_rows: list[dict[str, Any]] | None = None
    ) -> CuratedGitHubSource:
        df = pd.DataFrame(rows, columns=list(WORKFLOW_RUNS_COLUMNS.keys()))
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        df.to_csv(tmp.name, index=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        try:
            table, source, credential, _df, cleanup = create_data_warehouse_table_from_csv(
                csv_path=Path(tmp.name),
                table_name="github_workflow_runs",
                table_columns=WORKFLOW_RUNS_COLUMNS,
                test_bucket=TEST_BUCKET,
                team=self.team,
                source_prefix=GITHUB_SOURCE_PREFIX,
            )
        except PermissionError as err:
            self.skipTest(f"object storage unavailable: {err}")
        self.addCleanup(cleanup)
        jobs_table = None
        if job_rows is not None:
            jobs_df = pd.DataFrame(job_rows, columns=list(WORKFLOW_JOBS_COLUMNS.keys()))
            jobs_tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
            jobs_df.to_csv(jobs_tmp.name, index=False)
            jobs_tmp.close()
            self.addCleanup(Path(jobs_tmp.name).unlink, missing_ok=True)
            try:
                jobs_table, _source, _credential, _df, jobs_cleanup = create_data_warehouse_table_from_csv(
                    csv_path=Path(jobs_tmp.name),
                    table_name="github_workflow_jobs",
                    table_columns=WORKFLOW_JOBS_COLUMNS,
                    test_bucket=TEST_BUCKET,
                    team=self.team,
                    source=source,
                    credential=credential,
                    source_prefix=GITHUB_SOURCE_PREFIX,
                )
            except PermissionError as err:
                self.skipTest(f"object storage unavailable: {err}")
            self.addCleanup(jobs_cleanup)
        # pull_requests is never read by these detectors; reuse the runs table so for_team isn't needed.
        return CuratedGitHubSource(
            team=self.team,
            tables=GitHubTables(
                pull_requests=table.name,
                workflow_runs=table.name,
                workflow_jobs=jobs_table.name if jobs_table else None,
            ),
        )

    def test_flaky_check_detects_only_fail_then_rerun_pass(self) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [_run_row(1, "CI", "shaF", "success", now - timedelta(hours=19), 60, run_attempt=2)]
        jobs = [
            _job_row(100, 1, "flaky-job", "shaF", "failure", now - timedelta(hours=20), run_attempt=1),
            _job_row(101, 1, "flaky-job", "shaF", "success", now - timedelta(hours=19), run_attempt=2),
            _job_row(102, 1, "solid-job", "shaF", "success", now - timedelta(hours=19), run_attempt=1),
        ]
        findings = detect_flaky_checks(self._curated_over_runs(rows, jobs), min_flaky_runs=1)
        assert {f.extra["job_name"] for f in findings} == {"flaky-job"}
        assert findings[0].source_type == SOURCE_TYPE_FLAKY_CHECK
        assert findings[0].extra["flaky_count"] == 1
        assert findings[0].extra["run_id"] == 1
        assert findings[0].source_id.endswith(":2:flaky")

    def test_broken_master_fires_only_on_failing_default_branch(self) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            _run_row(
                1, "red-ci", "s1", "success", now - timedelta(hours=4), 30, head_branch="trunk", default_branch="trunk"
            ),
            _run_row(
                2, "red-ci", "s2", "failure", now - timedelta(hours=3), 30, head_branch="trunk", default_branch="trunk"
            ),
            _run_row(
                3, "red-ci", "s3", "failure", now - timedelta(hours=2), 30, head_branch="trunk", default_branch="trunk"
            ),
            _run_row(
                4,
                "legacy-ci",
                "s4",
                "failure",
                now - timedelta(hours=4),
                30,
                head_branch="master",
                default_branch="trunk",
            ),
            _run_row(
                5,
                "legacy-ci",
                "s5",
                "failure",
                now - timedelta(hours=3),
                30,
                head_branch="master",
                default_branch="trunk",
            ),
        ]
        findings = detect_broken_master(self._curated_over_runs(rows), min_runs=2)
        assert {f.extra["workflow_name"] for f in findings} == {"red-ci"}
        assert findings[0].source_type == SOURCE_TYPE_BROKEN_MASTER
        assert findings[0].extra["branch"] == "trunk"
        assert findings[0].source_id.endswith(":3:1:broken")

    def test_duration_regression_requires_absolute_and_relative_jump(self) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        current = now - timedelta(days=1)
        baseline = now - timedelta(days=8)
        rows = [
            # slow-ci: 10s baseline → 120s current (big absolute + relative jump) → regression.
            _run_row(1, "slow-ci", "c1", "success", current, 120),
            _run_row(2, "slow-ci", "c2", "success", current - timedelta(hours=1), 120),
            _run_row(3, "slow-ci", "b1", "success", baseline, 10),
            _run_row(4, "slow-ci", "b2", "success", baseline - timedelta(hours=1), 10),
            # steady-ci: 100s → 104s (+4% / +4s) — fails the absolute-jump guard → no signal.
            _run_row(5, "steady-ci", "c3", "success", current, 104),
            _run_row(6, "steady-ci", "c4", "success", current - timedelta(hours=1), 104),
            _run_row(7, "steady-ci", "b3", "success", baseline, 100),
            _run_row(8, "steady-ci", "b4", "success", baseline - timedelta(hours=1), 100),
            _run_row(9, "thin-ci", "c5", "success", current, 120),
            _run_row(10, "thin-ci", "c6", "failure", current - timedelta(hours=1), 120),
            _run_row(11, "thin-ci", "b5", "success", baseline, 10),
            _run_row(12, "thin-ci", "b6", "failure", baseline - timedelta(hours=1), 10),
        ]
        findings = detect_ci_duration_regressions(self._curated_over_runs(rows), min_runs=2)
        assert {f.extra["workflow_name"] for f in findings} == {"slow-ci"}
        assert findings[0].source_type == SOURCE_TYPE_DURATION_REGRESSION
