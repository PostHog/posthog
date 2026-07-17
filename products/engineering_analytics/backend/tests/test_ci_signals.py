import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

import pandas as pd
from asgiref.sync import async_to_sync

from posthog.rbac.user_access_control import UserAccessControl

from products.engineering_analytics.backend.logic.ci_signals_config import (
    AUTHORIZED_SOURCES_CONFIG_KEY,
    CI_SIGNAL_SOURCE_TYPES,
    DRY_RUN_CONFIG_KEY,
    is_dry_run,
    list_authorized_ci_signal_sources,
    update_ci_signals_config,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.signals.contracts import (
    SOURCE_PRODUCT,
    SOURCE_TYPE_BROKEN_DEFAULT_BRANCH,
    SOURCE_TYPE_DURATION_REGRESSION,
    SOURCE_TYPE_FLAKY_CHECK,
    CISignalFinding,
)
from products.engineering_analytics.backend.logic.signals.coordinator import (
    CISignalTarget,
    _detect_for_target,
    _record_emitted,
    _unemitted,
    detect_and_emit_ci_signals_activity,
)
from products.engineering_analytics.backend.logic.signals.detect import detect_for_source
from products.engineering_analytics.backend.logic.signals.detectors import (
    detect_all,
    detect_broken_default_branch,
    detect_ci_duration_regressions,
    detect_flaky_checks,
)
from products.engineering_analytics.backend.logic.sources import GitHubTables
from products.engineering_analytics.backend.logic.views.source_schema import (
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests.test_views import create_github_source, create_warehouse_table_row
from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP, SignalRemediation
from products.signals.backend.enums import ReportPriority
from products.signals.backend.facade.api import set_signal_source_types_enabled, validate_signal_input
from products.signals.backend.models import SignalEmissionRecord, SignalSourceConfig
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

_COORDINATOR = "products.engineering_analytics.backend.logic.signals.coordinator"
_DETECT = "products.engineering_analytics.backend.logic.signals.detect"
_DETECTORS = "products.engineering_analytics.backend.logic.signals.detectors"
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
    duration_seconds: int = 60,
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
        "completed_at": _ts(started + timedelta(seconds=duration_seconds)),
        "steps": "[]",
    }


def _assert_emittable(finding: CISignalFinding) -> None:
    # The exact emit-time check: detector payload drift would silently reject every signal in prod.
    validate_signal_input(
        source_product=SOURCE_PRODUCT,
        source_type=finding.source_type,
        source_id=finding.source_id,
        description=finding.description,
        weight=finding.weight,
        extra=finding.extra,
        remediation=finding.remediation,
    )


def test_source_type_constants_match_signals_taxonomy() -> None:
    # Guards the constants ↔ signals taxonomy mirror: a drift here makes emit_signal reject
    # every CI signal as an unknown source_product/source_type, silently emitting nothing.
    assert SOURCE_PRODUCT in {product.value for product in SignalSourceConfig.SourceProduct}
    for source_type in (SOURCE_TYPE_FLAKY_CHECK, SOURCE_TYPE_BROKEN_DEFAULT_BRANCH, SOURCE_TYPE_DURATION_REGRESSION):
        assert source_type in {choice.value for choice in SignalSourceConfig.SourceType}
        assert (SOURCE_PRODUCT, source_type) in SIGNAL_VARIANT_LOOKUP


def test_detect_all_raises_when_every_detector_fails() -> None:
    # A ClickHouse outage failing all three detectors must fail the activity so it retries and
    # alerts, not read as healthy CI with zero findings; one bad detector still must not
    # suppress the others' findings.
    curated = mock.Mock()
    boom = RuntimeError("clickhouse down")

    def failing(name: str) -> mock.Mock:
        return mock.Mock(side_effect=boom, __name__=name)

    with (
        mock.patch(f"{_DETECTORS}.detect_flaky_checks", failing("detect_flaky_checks")),
        mock.patch(f"{_DETECTORS}.detect_broken_default_branch", failing("detect_broken_default_branch")),
        mock.patch(f"{_DETECTORS}.detect_ci_duration_regressions", failing("detect_ci_duration_regressions")),
    ):
        with pytest.raises(RuntimeError):
            detect_all(curated)
    with (
        mock.patch(f"{_DETECTORS}.detect_flaky_checks", failing("detect_flaky_checks")),
        mock.patch(f"{_DETECTORS}.detect_broken_default_branch", return_value=[]),
        mock.patch(f"{_DETECTORS}.detect_ci_duration_regressions", return_value=[]),
    ):
        assert detect_all(curated) == []


class TestDetectForSourceMultiRepo(BaseTest):
    def test_multi_repo_source_snapshots_one_authorized_target(self) -> None:
        # One roster entry per configured repo must not become duplicate sweep targets:
        # duplicates would rescan every repo and race the emission ledger within one batch.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh-multi-snap",
            connection_id="gh-multi-snap",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix="multisnap_",
            job_inputs={"repositories": ["Acme/one", "Acme/two"]},
        )
        update_ci_signals_config(
            team=self.team,
            enabled=True,
            created_by_id=self.user.id,
            user_access_control=UserAccessControl(user=self.user, team=self.team),
        )
        authorized = list_authorized_ci_signal_sources(team=self.team)
        assert [entry.source_id for entry in authorized] == [str(source.id)]

    def test_detects_across_every_synced_repo_of_a_multi_repo_source(self) -> None:
        # A multi-repo source must contribute findings for each synced repo, not just the one the
        # bare (repo-less) resolver picks; a repo still backfilling an endpoint is skipped.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh-multi",
            connection_id="gh-multi",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix="multi_",
            job_inputs={"repositories": ["Acme/one", "Acme/two", "Acme/three"]},
        )
        repo_endpoints = {
            "Acme/one": ["pull_requests", "workflow_runs"],
            "Acme/two": ["pull_requests", "workflow_runs"],
            "Acme/three": ["pull_requests"],  # workflow_runs still syncing => repo not scanned
        }
        for repo, endpoints in repo_endpoints.items():
            slug = repo.replace("/", "_").lower()
            for endpoint in endpoints:
                ExternalDataSchema.objects.create(
                    team=self.team,
                    source=source,
                    name=f"{repo}.{endpoint}",
                    table=create_warehouse_table_row(self.team, name=f"multi_github_{slug}_{endpoint}", source=source),
                    should_sync=True,
                    sync_type_config={
                        "schema_metadata": {"source_repository": repo.lower(), "source_endpoint": endpoint}
                    },
                )

        def finding_for(curated: CuratedGitHubSource) -> list[CISignalFinding]:
            return [
                CISignalFinding(
                    source_type=SOURCE_TYPE_FLAKY_CHECK,
                    source_id=f"{curated.repository}:ci:flaky",
                    description=f"{curated.repository} finding",
                    weight=1.0,
                    remediation=SignalRemediation(human="h", agent="a"),
                )
            ]

        with mock.patch(f"{_DETECT}.detect_all", side_effect=finding_for):
            findings = detect_for_source(
                self.team, str(source.id), user_access_control=UserAccessControl(user=self.user, team=self.team)
            )
        assert {finding.source_id for finding in findings} == {"acme/one:ci:flaky", "acme/two:ci:flaky"}


class TestCISignalSourceAuthorization(BaseTest):
    def test_sweep_scans_only_the_snapshot_the_enabling_user_authorized(self) -> None:
        first = create_github_source(self.team, prefix="one_", source_id="gh-1")
        second = create_github_source(self.team, prefix="two_", source_id="gh-2")
        update_ci_signals_config(team=self.team, enabled=True, created_by_id=self.user.id)

        for row in SignalSourceConfig.objects.filter(team=self.team, source_product=SOURCE_PRODUCT):
            assert set(row.config[AUTHORIZED_SOURCES_CONFIG_KEY]) == {str(first.id), str(second.id)}
        authorized = list_authorized_ci_signal_sources(team=self.team)
        assert {source.source_id for source in authorized} == {str(first.id), str(second.id)}
        assert {source.authorized_by_user_id for source in authorized} == {self.user.id}

        # Connected after enabling => never authorized.
        create_github_source(self.team, prefix="three_", source_id="gh-3")
        assert {source.source_id for source in list_authorized_ci_signal_sources(team=self.team)} == {
            str(first.id),
            str(second.id),
        }

        second.deleted = True
        second.save()
        assert {source.source_id for source in list_authorized_ci_signal_sources(team=self.team)} == {str(first.id)}

        # Re-enabling without a config payload must not wipe the stored snapshot.
        set_signal_source_types_enabled(
            team_id=self.team.id,
            source_product=SOURCE_PRODUCT,
            source_types=CI_SIGNAL_SOURCE_TYPES,
            enabled=True,
            created_by_id=self.user.id,
        )
        assert {source.source_id for source in list_authorized_ci_signal_sources(team=self.team)} == {str(first.id)}

        self.user.is_active = False
        self.user.save()
        assert list_authorized_ci_signal_sources(team=self.team) == []
        self.user.is_active = True
        self.user.save()

        # An authorizer removed from the organization no longer authorizes anything — at discovery
        # and again at detection time (retries can run long after discovery).
        self.user.organization_memberships.all().delete()
        assert list_authorized_ci_signal_sources(team=self.team) == []
        target = CISignalTarget(team_id=self.team.id, source_id=str(first.id), authorized_by_user_id=self.user.id)
        with mock.patch(f"{_COORDINATOR}._rollout_flag_enabled", return_value=True):
            assert _detect_for_target(target) == ([], None)

    def test_rows_without_a_snapshot_authorize_nothing(self) -> None:
        create_github_source(self.team, prefix="one_", source_id="gh-1")
        for source_type in CI_SIGNAL_SOURCE_TYPES:
            SignalSourceConfig.objects.create(
                team=self.team,
                source_product=SOURCE_PRODUCT,
                source_type=source_type,
                enabled=True,
                config={},
                created_by=self.user,
            )
        assert list_authorized_ci_signal_sources(team=self.team) == []


class TestCISignalEmissionLedger(BaseTest):
    def _finding(self, source_id: str) -> CISignalFinding:
        return CISignalFinding(
            source_type=SOURCE_TYPE_FLAKY_CHECK,
            source_id=source_id,
            description="x",
            weight=1.0,
            remediation=SignalRemediation(human="h", agent="a", priority=ReportPriority.P2),
        )

    def test_unemitted_filters_recorded_findings(self) -> None:
        findings = [self._finding("a"), self._finding("b")]
        # A read alone records nothing, so a re-read still returns everything.
        assert {f.source_id for f in _unemitted(self.team, findings)} == {"a", "b"}
        assert {f.source_id for f in _unemitted(self.team, findings)} == {"a", "b"}
        # Recording one drops it from the next read; unrecorded and new conditions still come through.
        _record_emitted(self.team, self._finding("a"))
        assert {f.source_id for f in _unemitted(self.team, [*findings, self._finding("c")])} == {"b", "c"}

    def test_record_is_per_finding_so_a_failed_emit_is_retried(self) -> None:
        # The coordinator records only after a successful emit. A finding whose emit raised is never
        # recorded, so the next sweep re-detects and retries it rather than suppressing it for a week.
        findings = [self._finding("emitted"), self._finding("failed")]
        _record_emitted(self.team, findings[0])
        assert {f.source_id for f in _unemitted(self.team, findings)} == {"failed"}

    def test_activity_without_ai_approval_neither_emits_nor_records(self) -> None:
        # emit_signal silently returns when the org isn't AI-approved; recording before that would
        # bury the finding for its whole dedupe window. The activity gates approval up front instead.
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        target = CISignalTarget(team_id=self.team.id, source_id="gh-1", authorized_by_user_id=self.user.id)
        with (
            mock.patch(f"{_COORDINATOR}._detect_for_target", return_value=([self._finding("x")], self.team)),
            mock.patch(f"{_COORDINATOR}.emit_signal") as emit,
        ):
            result = async_to_sync(detect_and_emit_ci_signals_activity)(target)
        emit.assert_not_called()
        assert result["emitted"] == 0
        assert not SignalEmissionRecord.objects.filter(team=self.team).exists()

    def test_dry_run_reads_the_config_flag(self) -> None:
        update_ci_signals_config(team=self.team, enabled=True, created_by_id=self.user.id)
        assert is_dry_run(team=self.team) is False
        row = SignalSourceConfig.objects.get(
            team=self.team, source_product=SOURCE_PRODUCT, source_type=SOURCE_TYPE_FLAKY_CHECK
        )
        row.config = {**row.config, DRY_RUN_CONFIG_KEY: True}
        row.save(update_fields=["config"])
        assert is_dry_run(team=self.team) is True


class TestCISignalDetectors(ClickhouseTestMixin, BaseTest):
    """Detectors run over a real seeded github_workflow_runs warehouse table. Each test seeds both a
    should-fire and a should-not-fire workflow and asserts the detected set, so it catches both
    missed conditions and false positives. Skips when object storage is unreachable (no dev stack)."""

    def _seed_table(
        self,
        rows: list[dict[str, Any]],
        *,
        table_name: str,
        columns: dict[str, dict[str, str]],
        source: ExternalDataSource | None = None,
        credential: DataWarehouseCredential | None = None,
    ) -> tuple[DataWarehouseTable, ExternalDataSource, DataWarehouseCredential]:
        df = pd.DataFrame(rows, columns=list(columns.keys()))
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        df.to_csv(tmp.name, index=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        try:
            table, out_source, out_credential, _df, cleanup = create_data_warehouse_table_from_csv(
                csv_path=Path(tmp.name),
                table_name=table_name,
                table_columns=columns,
                test_bucket=TEST_BUCKET,
                team=self.team,
                source=source,
                credential=credential,
                source_prefix=GITHUB_SOURCE_PREFIX,
            )
        except PermissionError as err:
            self.skipTest(f"object storage unavailable: {err}")
        self.addCleanup(cleanup)
        return table, out_source, out_credential

    def _curated_over_runs(
        self, rows: list[dict[str, Any]], job_rows: list[dict[str, Any]] | None = None
    ) -> CuratedGitHubSource:
        table, source, credential = self._seed_table(
            rows, table_name="github_workflow_runs", columns=WORKFLOW_RUNS_COLUMNS
        )
        jobs_table = None
        if job_rows is not None:
            jobs_table, _source, _credential = self._seed_table(
                job_rows,
                table_name="github_workflow_jobs",
                columns=WORKFLOW_JOBS_COLUMNS,
                source=source,
                credential=credential,
            )
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
        assert findings[0].source_id.endswith(":flaky")
        _assert_emittable(findings[0])

    def test_flaky_source_ids_are_collision_free_and_bounded(self) -> None:
        # (workflow='build', job='test:linux') and (workflow='build:test', job='linux') would share
        # a ledger key with naive ':' joins, letting one condition suppress the other's emission;
        # an oversized name would exceed the ledger column, fail to record after emit, and re-emit
        # every sweep.
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [_run_row(1, "CI", "shaC", "success", now - timedelta(hours=19), 60, run_attempt=2)]
        jobs = []
        for offset, (workflow, job) in enumerate([("build", "test:linux"), ("build:test", "linux"), ("CI", "j" * 400)]):
            failed = _job_row(200 + offset * 2, 1, job, "shaC", "failure", now - timedelta(hours=20), run_attempt=1)
            passed = _job_row(201 + offset * 2, 1, job, "shaC", "success", now - timedelta(hours=19), run_attempt=2)
            failed["workflow_name"] = workflow
            passed["workflow_name"] = workflow
            jobs.extend([failed, passed])
        findings = detect_flaky_checks(self._curated_over_runs(rows, jobs), min_flaky_runs=1)
        ids = [finding.source_id for finding in findings]
        assert len(ids) == 3
        assert len(set(ids)) == 3
        assert max(len(source_id) for source_id in ids) <= 200

    def test_flaky_check_emits_one_signal_per_job_per_week_not_per_rerun(self) -> None:
        # The sweep re-reads a rolling window hourly. Keying a recurring flake per rerun turned 51
        # flaky jobs into 905 signals against real PostHog/posthog data — one card per occurrence.
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            _run_row(run_id, "CI", f"sha{run_id}", "success", now - timedelta(hours=run_id), 60, run_attempt=2)
            for run_id in (1, 2, 3)
        ]
        jobs = []
        for run_id in (1, 2, 3):
            jobs.append(
                _job_row(
                    run_id * 10,
                    run_id,
                    "flaky-job",
                    f"sha{run_id}",
                    "failure",
                    now - timedelta(hours=run_id),
                    run_attempt=1,
                )
            )
            jobs.append(
                _job_row(
                    run_id * 10 + 1,
                    run_id,
                    "flaky-job",
                    f"sha{run_id}",
                    "success",
                    now - timedelta(hours=run_id),
                    run_attempt=2,
                )
            )
        findings = detect_flaky_checks(self._curated_over_runs(rows, jobs), min_flaky_runs=3)
        assert len(findings) == 1
        assert findings[0].extra["flaky_count"] == 3
        # The most recent sighting is the worked example; the rest survive as the count.
        assert findings[0].extra["run_id"] == 3
        _assert_emittable(findings[0])

    def test_flaky_check_ignores_required_check_aggregators(self) -> None:
        # A `* Pass` gate fails only because a job it gates failed, so counting it emits a second
        # signal for every real flake. Real aggregators settle in 3-5s; real jobs run 60s+.
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [_run_row(1, "CI", "shaG", "success", now - timedelta(hours=2), 60, run_attempt=2)]
        jobs = [
            _job_row(
                200, 1, "Tests Pass", "shaG", "failure", now - timedelta(hours=3), run_attempt=1, duration_seconds=3
            ),
            _job_row(
                201, 1, "Tests Pass", "shaG", "success", now - timedelta(hours=2), run_attempt=2, duration_seconds=3
            ),
            _job_row(202, 1, "real-test-job", "shaG", "failure", now - timedelta(hours=3), run_attempt=1),
            _job_row(203, 1, "real-test-job", "shaG", "success", now - timedelta(hours=2), run_attempt=2),
        ]
        findings = detect_flaky_checks(self._curated_over_runs(rows, jobs), min_flaky_runs=1)
        assert {f.extra["job_name"] for f in findings} == {"real-test-job"}

    def test_broken_default_branch_fires_only_on_failing_default_branch(self) -> None:
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
        findings = detect_broken_default_branch(self._curated_over_runs(rows), min_runs=2)
        assert {f.extra["workflow_name"] for f in findings} == {"red-ci"}
        assert findings[0].source_type == SOURCE_TYPE_BROKEN_DEFAULT_BRANCH
        assert findings[0].extra["branch"] == "trunk"
        _assert_emittable(findings[0])

        # A still-red branch must dedupe against one weekly key: a new completed run changing the
        # source_id would re-emit the same standing condition on every hourly sweep.
        rows.append(
            _run_row(
                6, "red-ci", "s6", "failure", now - timedelta(hours=1), 30, head_branch="trunk", default_branch="trunk"
            )
        )
        refreshed = detect_broken_default_branch(self._curated_over_runs(rows), min_runs=2)
        assert refreshed[0].source_id == findings[0].source_id

    def test_broken_default_branch_does_not_count_cancelled_runs_as_failures(self) -> None:
        # A concurrency group cancelling superseded trunk runs is normal, not a red branch. Counting
        # cancelled runs against the rate pins heavy-cancel workflows permanently under the floor,
        # which made the guard a no-op and fired P1 on every transient red.
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            _run_row(
                index, "busy-ci", f"c{index}", "cancelled", now - timedelta(hours=index), 30, default_branch="main"
            )
            for index in range(1, 9)
        ]
        rows += [
            _run_row(20, "busy-ci", "ok1", "success", now - timedelta(hours=10), 30, default_branch="main"),
            _run_row(21, "busy-ci", "ok2", "success", now - timedelta(hours=11), 30, default_branch="main"),
            # Latest completed run is a decisive failure, but 2 of 3 conclusive runs passed.
            _run_row(22, "busy-ci", "bad", "failure", now - timedelta(minutes=30), 30, default_branch="main"),
        ]
        assert detect_broken_default_branch(self._curated_over_runs(rows), min_runs=2) == []

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
        _assert_emittable(findings[0])
