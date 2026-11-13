import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

import pandas as pd
from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.engineering_analytics.backend.facade.contracts import CISignalsSyncStatus
from products.engineering_analytics.backend.logic.ci_signals_config import (
    AUTHORIZED_SOURCES_CONFIG_KEY,
    CI_SIGNAL_REQUIRED_SCHEMAS,
    CI_SIGNAL_SOURCE_TYPES,
    DRY_RUN_CONFIG_KEY,
    _sync_status,
    is_dry_run,
    list_authorized_ci_signal_sources,
    update_ci_signals_config,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.workflow_flakiness import BY_DESIGN_FAILURES, FlakyJobRun
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
    _rollout_flag_enabled,
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
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _pr_row,
    create_github_source,
    create_warehouse_table_row,
    seeding_object_storage,
)
from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP
from products.signals.backend.facade.api import set_signal_source_types_enabled, validate_signal_input
from products.signals.backend.facade.taxonomy import ReportPriority, SignalRemediation
from products.signals.backend.models import SignalEmissionRecord, SignalSourceConfig
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv
from products.warehouse_sources.backend.facade.types import (
    ExternalDataSchemaStatus,
    ExternalDataSourceStatus,
    ExternalDataSourceType,
)

_BY_DESIGN_JOB_NAMES = [entry.split("/", 2)[2] for entry in BY_DESIGN_FAILURES]

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
    repository: str = "PostHog/posthog",
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
        # The webhook lands a minimal `repository` payload with no default_branch, so the fixture omits it too.
        "repository": json.dumps({"full_name": repository}),
    }


def _default_branch_pr_row(
    number: int, updated: datetime, *, default_branch: str, repo: str = "PostHog/posthog"
) -> dict[str, Any]:
    return _pr_row(number, "dev", "open", 0, _ts(updated), full_name=repo, default_branch=default_branch)


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
    assert SOURCE_PRODUCT in {product.value for product in SignalSourceConfig.SourceProduct}
    for source_type in (SOURCE_TYPE_FLAKY_CHECK, SOURCE_TYPE_BROKEN_DEFAULT_BRANCH, SOURCE_TYPE_DURATION_REGRESSION):
        assert source_type in {choice.value for choice in SignalSourceConfig.SourceType}
        assert (SOURCE_PRODUCT, source_type) in SIGNAL_VARIANT_LOOKUP


def test_detect_all_raises_when_every_detector_fails() -> None:
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


def _flaky_row(job_name: str, run_id: int, *, workflow_name: str = "CI", head_sha: str = "sha") -> FlakyJobRun:
    return FlakyJobRun(
        repo_owner="PostHog",
        repo_name="posthog",
        workflow_name=workflow_name,
        job_name=job_name,
        run_id=run_id,
        head_sha=head_sha,
        failed_attempt=1,
        passed_attempt=2,
    )


def _detect_flaky_over(rows: list[FlakyJobRun], *, min_flaky_runs: int) -> list[CISignalFinding]:
    with mock.patch(f"{_DETECTORS}.query_workflow_flakiness", return_value=rows):
        return detect_flaky_checks(mock.Mock(), min_flaky_runs=min_flaky_runs)


def test_flaky_source_ids_are_collision_free_and_bounded() -> None:
    # A plain ':' join of workflow and job would give the first two rows the same ledger key.
    rows = [
        _flaky_row("test:linux", 1, workflow_name="build"),
        _flaky_row("linux", 1, workflow_name="build:test"),
        _flaky_row("j" * 400, 1),
    ]
    ids = [finding.source_id for finding in _detect_flaky_over(rows, min_flaky_runs=1)]
    assert len(ids) == 3
    assert len(set(ids)) == 3
    assert max(len(source_id) for source_id in ids) <= 200


def test_flaky_check_emits_one_signal_per_job_per_week_not_per_rerun() -> None:
    rows = [_flaky_row("flaky-job", run_id, head_sha=f"sha{run_id}") for run_id in (1, 2, 3)]
    findings = _detect_flaky_over(rows, min_flaky_runs=3)
    assert len(findings) == 1
    assert findings[0].extra["flaky_count"] == 3
    assert findings[0].extra["run_id"] == 3
    _assert_emittable(findings[0])


def test_flaky_check_groups_a_sharded_job_under_one_signal() -> None:
    # The shard label sits mid-name, so an end-anchored match would not group these.
    shards = [
        "Product tests (warehouse-sources (1/4), events schema legacy)",
        "Product tests (warehouse-sources (1/5), events schema legacy)",
        "Product tests (warehouse-sources (1/6), events schema legacy)",
    ]
    rows = [_flaky_row(shard, run_id, head_sha=f"shaS{run_id}") for run_id, shard in enumerate(shards, start=1)]
    findings = _detect_flaky_over(rows, min_flaky_runs=3)
    assert len(findings) == 1
    assert "CI job 'Product tests (warehouse-sources, events schema legacy)'" in findings[0].description
    assert findings[0].extra["job_name"] == "Product tests (warehouse-sources (1/6), events schema legacy)"
    assert findings[0].extra["flaky_count"] == 3
    assert "Product tests (warehouse-sources (1/6), events schema legacy)" in findings[0].description
    # `(1/4)`..`(1/6)` are all shard slot 1, so no multi-shard spread is claimed.
    assert "spread over" not in findings[0].description
    _assert_emittable(findings[0])


def test_flaky_check_counts_runs_not_shard_recoveries() -> None:
    rows = [
        _flaky_row(f"Product tests (warehouse-sources ({index}/6), events schema legacy)", 1) for index in (1, 2, 3)
    ]
    assert _detect_flaky_over(rows, min_flaky_runs=3) == []


class TestDetectForSourceMultiRepo(BaseTest):
    def test_multi_repo_source_snapshots_one_authorized_target(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh-multi-snap",
            connection_id="gh-multi-snap",
            status=ExternalDataSourceStatus.COMPLETED,
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
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh-multi",
            connection_id="gh-multi",
            status=ExternalDataSourceStatus.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix="multi_",
            job_inputs={"repositories": ["Acme/one", "Acme/two", "Acme/three"]},
        )
        repo_endpoints = {
            "Acme/one": ["pull_requests", "workflow_runs"],
            "Acme/two": ["pull_requests", "workflow_runs"],
            "Acme/three": ["pull_requests"],  # No workflow_runs schema, so this repo is not scanned.
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

    def _two_synced_repo_source(self) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="gh-sib",
            connection_id="gh-sib",
            status=ExternalDataSourceStatus.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix="sib_",
            job_inputs={"repositories": ["Acme/one", "Acme/two"]},
        )
        for repo in ("Acme/one", "Acme/two"):
            slug = repo.replace("/", "_").lower()
            for endpoint in ("pull_requests", "workflow_runs"):
                ExternalDataSchema.objects.create(
                    team=self.team,
                    source=source,
                    name=f"{repo}.{endpoint}",
                    table=create_warehouse_table_row(self.team, name=f"sib_github_{slug}_{endpoint}", source=source),
                    should_sync=True,
                    sync_type_config={
                        "schema_metadata": {"source_repository": repo.lower(), "source_endpoint": endpoint}
                    },
                )
        return source

    def test_one_repos_total_failure_does_not_abort_sibling_repos(self) -> None:
        source = self._two_synced_repo_source()
        uac = UserAccessControl(user=self.user, team=self.team)

        def one_repo_fails(curated: CuratedGitHubSource) -> list[CISignalFinding]:
            if curated.repository.casefold() == "acme/one":
                raise RuntimeError("clickhouse down for this repo")
            return [
                CISignalFinding(
                    source_type=SOURCE_TYPE_FLAKY_CHECK,
                    source_id=f"{curated.repository}:ci:flaky",
                    description=f"{curated.repository} finding",
                    weight=1.0,
                    remediation=SignalRemediation(human="h", agent="a"),
                )
            ]

        with mock.patch(f"{_DETECT}.detect_all", side_effect=one_repo_fails):
            findings = detect_for_source(self.team, str(source.id), user_access_control=uac)
        assert {finding.source_id for finding in findings} == {"acme/two:ci:flaky"}

    def test_all_repos_failing_re_raises_so_the_activity_retries(self) -> None:
        source = self._two_synced_repo_source()
        uac = UserAccessControl(user=self.user, team=self.team)
        with mock.patch(f"{_DETECT}.detect_all", side_effect=RuntimeError("clickhouse down")):
            with pytest.raises(RuntimeError):
                detect_for_source(self.team, str(source.id), user_access_control=uac)


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

        # A source connected after enabling is not in the snapshot.
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

        # Detection checks membership again because retries can run long after discovery.
        self.user.organization_memberships.all().delete()
        assert list_authorized_ci_signal_sources(team=self.team) == []
        target = CISignalTarget(team_id=self.team.id, source_id=str(first.id), authorized_by_user_id=self.user.id)
        with mock.patch(f"{_COORDINATOR}._rollout_flag_enabled", return_value=True):
            assert _detect_for_target(target) == ([], None)

    def test_rollout_flag_is_evaluated_as_the_enabling_user(self) -> None:
        # The flag's release condition is a person cohort, which a synthetic team-scoped distinct_id never matches.
        with mock.patch("posthoganalytics.feature_enabled", return_value=True) as flag_check:
            assert _rollout_flag_enabled(self.team, self.user)
        assert flag_check.call_args.args[1] == (self.user.distinct_id or str(self.user.uuid))

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
        assert {f.source_id for f in _unemitted(self.team, findings)} == {"a", "b"}
        assert {f.source_id for f in _unemitted(self.team, findings)} == {"a", "b"}
        _record_emitted(self.team, self._finding("a"))
        assert {f.source_id for f in _unemitted(self.team, [*findings, self._finding("c")])} == {"b", "c"}

    def test_record_is_per_finding_so_a_failed_emit_is_retried(self) -> None:
        findings = [self._finding("emitted"), self._finding("failed")]
        _record_emitted(self.team, findings[0])
        assert {f.source_id for f in _unemitted(self.team, findings)} == {"failed"}

    def test_activity_without_ai_approval_neither_emits_nor_records(self) -> None:
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

    def test_finding_of_a_disabled_source_type_is_not_emitted_or_recorded(self) -> None:
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        target = CISignalTarget(team_id=self.team.id, source_id="gh-1", authorized_by_user_id=self.user.id)
        with (
            mock.patch(f"{_COORDINATOR}._detect_for_target", return_value=([self._finding("x")], self.team)),
            mock.patch(f"{_COORDINATOR}.is_signal_source_enabled", return_value=False),
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

    def test_re_enable_preserves_operator_config_keys(self) -> None:
        create_github_source(self.team, prefix="one_", source_id="gh-dry")
        update_ci_signals_config(team=self.team, enabled=True, created_by_id=self.user.id)
        for row in SignalSourceConfig.objects.filter(team=self.team, source_product=SOURCE_PRODUCT):
            row.config = {**row.config, DRY_RUN_CONFIG_KEY: True}
            row.save(update_fields=["config"])
        update_ci_signals_config(team=self.team, enabled=False, created_by_id=self.user.id)
        update_ci_signals_config(team=self.team, enabled=True, created_by_id=self.user.id)
        assert is_dry_run(team=self.team) is True
        row = SignalSourceConfig.objects.get(
            team=self.team, source_product=SOURCE_PRODUCT, source_type=SOURCE_TYPE_FLAKY_CHECK
        )
        assert row.config[AUTHORIZED_SOURCES_CONFIG_KEY]


class TestSyncStatus(BaseTest):
    def _github_source_with_schemas(
        self, *, source_id: str, repo: str, statuses: dict[str, ExternalDataSchemaStatus]
    ) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=source_id,
            connection_id=source_id,
            status=ExternalDataSourceStatus.COMPLETED,
            source_type=ExternalDataSourceType.GITHUB,
            prefix=f"{source_id.replace('-', '')}_",
            job_inputs={"repositories": [repo]},
        )
        for endpoint, status in statuses.items():
            ExternalDataSchema.objects.create(
                team=self.team,
                source=source,
                name=f"{repo}.{endpoint}",
                should_sync=True,
                status=status,
                sync_type_config={"schema_metadata": {"source_repository": repo, "source_endpoint": endpoint}},
            )

    @parameterized.expand(
        [
            ("all_completed", {}, CISignalsSyncStatus.COMPLETED),
            ("one_failed", {"workflow_runs": ExternalDataSchemaStatus.FAILED}, CISignalsSyncStatus.FAILED),
            ("one_running", {"workflow_jobs": ExternalDataSchemaStatus.RUNNING}, CISignalsSyncStatus.RUNNING),
        ]
    )
    def test_sync_status_resolves_repo_qualified_schema_names(
        self, _name: str, overrides: dict[str, ExternalDataSchemaStatus], expected: CISignalsSyncStatus
    ) -> None:
        statuses = dict.fromkeys(CI_SIGNAL_REQUIRED_SCHEMAS, ExternalDataSchemaStatus.COMPLETED)
        statuses.update(overrides)
        self._github_source_with_schemas(source_id="gh-sync", repo="acme/one", statuses=statuses)
        assert _sync_status(self.team, None) == expected

    def test_source_without_ci_schemas_does_not_gate_completion(self) -> None:
        self._github_source_with_schemas(
            source_id="gh-ci",
            repo="acme/one",
            statuses=dict.fromkeys(CI_SIGNAL_REQUIRED_SCHEMAS, ExternalDataSchemaStatus.COMPLETED),
        )
        self._github_source_with_schemas(
            source_id="gh-issues", repo="acme/two", statuses={"issues": ExternalDataSchemaStatus.RUNNING}
        )
        assert _sync_status(self.team, None) == CISignalsSyncStatus.COMPLETED


class TestCISignalDetectors(ClickhouseTestMixin, BaseTest):
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
        with seeding_object_storage(self):
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
        self.addCleanup(cleanup)
        return table, out_source, out_credential

    def _curated_over_runs(
        self,
        rows: list[dict[str, Any]],
        job_rows: list[dict[str, Any]] | None = None,
        pr_rows: list[dict[str, Any]] | None = None,
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
        # The curated run source always joins the PR snapshot, so the table must exist even when it is empty.
        prs_table, _source, _credential = self._seed_table(
            pr_rows or [],
            table_name="github_pull_requests",
            columns=PULL_REQUESTS_COLUMNS,
            source=source,
            credential=credential,
        )
        return CuratedGitHubSource(
            team=self.team,
            tables=GitHubTables(
                pull_requests=prs_table.name,
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

    def test_flaky_query_keeps_same_commit_reruns_as_distinct_runs(self) -> None:
        # The runs share one head_sha, so a query that groups without run_id would collapse them into one row.
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            _run_row(run_id, "CI", "shaR", "success", now - timedelta(hours=run_id + 1), 60, run_attempt=2)
            for run_id in (1, 2, 3)
        ]
        jobs = []
        for run_id in (1, 2, 3):
            started = now - timedelta(hours=run_id + 1)
            jobs.append(_job_row(run_id * 10, run_id, "flaky-job", "shaR", "failure", started, run_attempt=1))
            jobs.append(_job_row(run_id * 10 + 1, run_id, "flaky-job", "shaR", "success", started, run_attempt=2))

        findings = detect_flaky_checks(self._curated_over_runs(rows, jobs), min_flaky_runs=3)

        assert len(findings) == 1
        assert findings[0].extra["flaky_count"] == 3

    @parameterized.expand(
        [
            # 3s is under NO_OP_JOB_MAX_SECONDS, which drops this gate job.
            ("Tests Pass", 3),
            # 46s clears the duration floor, so only BY_DESIGN_FAILURES can drop these.
            *[(name, 46) for name in _BY_DESIGN_JOB_NAMES],
        ]
    )
    def test_flaky_check_ignores_excluded_jobs(self, job_name: str, duration_seconds: int) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [_run_row(1, "CI", "shaG", "success", now - timedelta(hours=2), 60, run_attempt=2)]
        jobs = [
            _job_row(
                200,
                1,
                job_name,
                "shaG",
                "failure",
                now - timedelta(hours=3),
                run_attempt=1,
                duration_seconds=duration_seconds,
            ),
            _job_row(
                201,
                1,
                job_name,
                "shaG",
                "success",
                now - timedelta(hours=2),
                run_attempt=2,
                duration_seconds=duration_seconds,
            ),
            _job_row(202, 1, "real-test-job", "shaG", "failure", now - timedelta(hours=3), run_attempt=1),
            _job_row(203, 1, "real-test-job", "shaG", "success", now - timedelta(hours=2), run_attempt=2),
        ]
        findings = detect_flaky_checks(self._curated_over_runs(rows, jobs), min_flaky_runs=1)
        assert {f.extra["job_name"] for f in findings} == {"real-test-job"}

    def test_flaky_check_reports_by_design_job_names_in_another_repo(self) -> None:
        job_name = _BY_DESIGN_JOB_NAMES[0]
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            _run_row(1, "CI", "shaS", "success", now - timedelta(hours=2), 60, run_attempt=2, repository="acme/webapp")
        ]
        jobs = [
            _job_row(300, 1, job_name, "shaS", "failure", now - timedelta(hours=3), run_attempt=1, duration_seconds=46),
            _job_row(301, 1, job_name, "shaS", "success", now - timedelta(hours=2), run_attempt=2, duration_seconds=46),
        ]
        findings = detect_flaky_checks(self._curated_over_runs(rows, jobs), min_flaky_runs=1)
        assert {f.extra["job_name"] for f in findings} == {job_name}

    def test_broken_default_branch_fires_only_on_failing_default_branch(self) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            _run_row(1, "red-ci", "s1", "success", now - timedelta(hours=4), 30, head_branch="trunk"),
            _run_row(2, "red-ci", "s2", "failure", now - timedelta(hours=3), 30, head_branch="trunk"),
            _run_row(3, "red-ci", "s3", "failure", now - timedelta(hours=2), 30, head_branch="trunk"),
            _run_row(4, "legacy-ci", "s4", "failure", now - timedelta(hours=4), 30, head_branch="master"),
            _run_row(5, "legacy-ci", "s5", "failure", now - timedelta(hours=3), 30, head_branch="master"),
        ]
        # The older PR reports the default branch from before a rename. The newer report must win, or legacy-ci would fire.
        prs = [
            _default_branch_pr_row(1, now - timedelta(days=30), default_branch="master"),
            _default_branch_pr_row(2, now - timedelta(days=1), default_branch="trunk"),
        ]
        # Each detector call keys its source_id on the observation week, so both calls must read one clock.
        with time_machine.travel(now, tick=False):
            findings = detect_broken_default_branch(self._curated_over_runs(rows, pr_rows=prs), min_runs=2)
            assert {f.extra["workflow_name"] for f in findings} == {"red-ci"}
            assert findings[0].source_type == SOURCE_TYPE_BROKEN_DEFAULT_BRANCH
            assert findings[0].extra["branch"] == "trunk"
            _assert_emittable(findings[0])

            rows.append(_run_row(6, "red-ci", "s6", "failure", now - timedelta(hours=1), 30, head_branch="trunk"))
            refreshed = detect_broken_default_branch(self._curated_over_runs(rows, pr_rows=prs), min_runs=2)
            assert refreshed[0].source_id == findings[0].source_id

    def test_broken_default_branch_without_pr_evidence_never_guesses(self) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            _run_row(1, "red-ci", "s1", "failure", now - timedelta(hours=3), 30, head_branch="master"),
            _run_row(2, "red-ci", "s2", "failure", now - timedelta(hours=2), 30, head_branch="master"),
        ]
        prs = [_default_branch_pr_row(1, now - timedelta(days=1), default_branch="master", repo="Acme/other")]
        assert detect_broken_default_branch(self._curated_over_runs(rows, pr_rows=prs), min_runs=2) == []

    def test_broken_default_branch_does_not_count_cancelled_runs_as_failures(self) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = [
            _run_row(index, "busy-ci", f"c{index}", "cancelled", now - timedelta(hours=index), 30)
            for index in range(1, 9)
        ]
        rows += [
            _run_row(20, "busy-ci", "ok1", "success", now - timedelta(hours=10), 30),
            _run_row(21, "busy-ci", "ok2", "success", now - timedelta(hours=11), 30),
            # The latest run failed, but 2 of the 3 runs with a verdict passed.
            _run_row(22, "busy-ci", "bad", "failure", now - timedelta(minutes=30), 30),
        ]
        prs = [_default_branch_pr_row(1, now - timedelta(days=1), default_branch="main")]
        assert detect_broken_default_branch(self._curated_over_runs(rows, pr_rows=prs), min_runs=2) == []

    def test_duration_regression_requires_absolute_and_relative_jump(self) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        current = now - timedelta(days=1)
        baseline = now - timedelta(days=8)
        rows = [
            # slow-ci: 10s to 120s clears both gates.
            _run_row(1, "slow-ci", "c1", "success", current, 120),
            _run_row(2, "slow-ci", "c2", "success", current - timedelta(hours=1), 120),
            _run_row(3, "slow-ci", "b1", "success", baseline, 10),
            _run_row(4, "slow-ci", "b2", "success", baseline - timedelta(hours=1), 10),
            # long-ci: 1000s to 1350s clears both gates without doubling.
            _run_row(13, "long-ci", "c7", "success", current, 1350),
            _run_row(14, "long-ci", "c8", "success", current - timedelta(hours=1), 1350),
            _run_row(15, "long-ci", "b7", "success", baseline, 1000),
            _run_row(16, "long-ci", "b8", "success", baseline - timedelta(hours=1), 1000),
            # steady-ci: 100s to 104s fails the absolute gate.
            _run_row(5, "steady-ci", "c3", "success", current, 104),
            _run_row(6, "steady-ci", "c4", "success", current - timedelta(hours=1), 104),
            _run_row(7, "steady-ci", "b3", "success", baseline, 100),
            _run_row(8, "steady-ci", "b4", "success", baseline - timedelta(hours=1), 100),
            # mild-ci: 950s to 1100s clears the absolute gate but fails the relative gate.
            _run_row(17, "mild-ci", "c9", "success", current, 1100),
            _run_row(18, "mild-ci", "c10", "success", current - timedelta(hours=1), 1100),
            _run_row(19, "mild-ci", "b9", "success", baseline, 950),
            _run_row(20, "mild-ci", "b10", "success", baseline - timedelta(hours=1), 950),
            _run_row(9, "thin-ci", "c5", "success", current, 120),
            _run_row(10, "thin-ci", "c6", "failure", current - timedelta(hours=1), 120),
            _run_row(11, "thin-ci", "b5", "success", baseline, 10),
            _run_row(12, "thin-ci", "b6", "failure", baseline - timedelta(hours=1), 10),
        ]
        findings = detect_ci_duration_regressions(self._curated_over_runs(rows), min_runs=2)
        assert {f.extra["workflow_name"] for f in findings} == {"slow-ci", "long-ci"}
        for finding in findings:
            assert finding.source_type == SOURCE_TYPE_DURATION_REGRESSION
            _assert_emittable(finding)

    def test_duration_regression_ignores_no_op_dominated_windows(self) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        current = now - timedelta(days=1)
        baseline = now - timedelta(days=8)
        rows = [
            _run_row(1, "gated-ci", "c1", "success", current, 120),
            _run_row(2, "gated-ci", "c2", "success", current - timedelta(hours=1), 5),
            _run_row(3, "gated-ci", "c3", "success", current - timedelta(hours=2), 5),
            _run_row(4, "gated-ci", "b1", "success", baseline, 10),
            _run_row(5, "gated-ci", "b2", "success", baseline - timedelta(hours=1), 5),
            _run_row(6, "gated-ci", "b3", "success", baseline - timedelta(hours=2), 5),
        ]
        # Each window has 3 successful runs but only 1 that is not a 5s no-op, which is under min_runs.
        findings = detect_ci_duration_regressions(self._curated_over_runs(rows), min_runs=2)
        assert findings == []
