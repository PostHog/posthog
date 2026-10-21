from datetime import UTC, datetime
from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.hogql.database.database import Database

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.ad_hoc_sync import AdHocSyncTrigger, WorkflowStartError
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataSourceDestination
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_PINNED_METADATA_KEY,
    ExternalDataSchema,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.self_managed_migration import (
    MIGRATION_MARKER_KEY,
    MigrationOptions,
    TableMigrationState,
    abandon_tables,
    evaluate_tables,
    migrate_self_managed_tables,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store import source_base
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    parse_self_managed_url,
    table_definition_for,
)
from products.warehouse_sources.backend.types import DataWarehouseTableFormat, ExternalDataJobStatus

MODULE = "products.warehouse_sources.backend.self_managed_migration"
SOURCE_VIEWS = "products.warehouse_sources.backend.presentation.views.external_data_source"
EXPORTS_URL = "https://exports.s3.eu-west-1.amazonaws.com/orders/*.csv"


def _no_region(_bucket: str, _credential: SelfManagedCredential) -> str | None:
    raise AssertionError("every URL in this test names its region")


def _update_marker(table: DataWarehouseTable, **changes: Any) -> None:
    table.refresh_from_db()
    table.options = {**table.options, MIGRATION_MARKER_KEY: {**table.options[MIGRATION_MARKER_KEY], **changes}}
    table.save(update_fields=["options"])


class TestSelfManagedMigration(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.trigger_count = 0
        self.workflow_ids: list[str] = []
        patches = [
            patch(f"{MODULE}.source_feature_flag_missing", return_value=False),
            patch(f"{MODULE}.sync_external_data_job_workflow"),
            patch(f"{MODULE}.trigger_ad_hoc_sync", side_effect=self._trigger),
            patch(f"{MODULE}.delete_external_data_schedule"),
            # The location check resolves the bucket host, and these example buckets don't exist.
            patch.object(source_base, "validate_warehouse_table_url_pattern", return_value=(True, "")),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.flag_missing, self.sync_schedule, self.trigger, self.delete_schedule, _ = mocks
        self.credential = self._credential("AKIAFIRST")

    def _trigger(self, *_args: Any, **kwargs: Any) -> AdHocSyncTrigger:
        self.trigger_count += 1
        self.workflow_ids.append(kwargs["workflow_id"])
        return AdHocSyncTrigger(workflow_id=kwargs["workflow_id"], schedule_paused_now=False)

    def _marker(self, table: DataWarehouseTable) -> dict[str, Any]:
        table.refresh_from_db()
        return table.options[MIGRATION_MARKER_KEY]

    def _credential(self, access_key: str) -> DataWarehouseCredential:
        return DataWarehouseCredential.objects.create(access_key=access_key, access_secret="c2VjcmV0", team=self.team)

    def _table(
        self,
        name: str = "orders",
        url: str = EXPORTS_URL,
        credential: DataWarehouseCredential | None = None,
        table_format: str = DataWarehouseTableFormat.CSVWithNames,
        created_at: datetime | None = None,
        **fields: Any,
    ) -> DataWarehouseTable:
        table = DataWarehouseTable.objects.create(
            name=name,
            format=table_format,
            url_pattern=url,
            team=self.team,
            credential=credential or self.credential,
            columns={"Order ID": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField", "valid": True}},
            options={"csv_allow_double_quotes": True},
            **fields,
        )
        if created_at is not None:
            DataWarehouseTable.raw_objects.filter(pk=table.pk).update(created_at=created_at)
            table.refresh_from_db()
        return table

    def _migrate(self, **options: Any) -> list[Any]:
        resolve_region = options.pop("resolve_region", _no_region)
        live_run = options.pop("live_run", True)
        return migrate_self_managed_tables(
            MigrationOptions(team_id=self.team.pk, live_run=live_run, **options),
            client=MagicMock(),
            resolve_region=resolve_region,
        )

    def _states(self) -> dict[str, TableMigrationState]:
        return {
            status.name: status.state for status in evaluate_tables(team_id=self.team.pk, resolve_region=_no_region)
        }

    def _schema_for(self, table: DataWarehouseTable) -> ExternalDataSchema:
        return ExternalDataSchema.objects.select_related("source").get(table=table, deleted=False)

    def _job(self, table: DataWarehouseTable, status: str, latest_error: str | None = None) -> ExternalDataJob:
        schema = self._schema_for(table)
        return ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=status,
            billable=False,
            latest_error=latest_error,
        )

    def test_tables_group_into_one_source_per_credential_and_bucket(self) -> None:
        other_credential = self._credential("AKIASECOND")
        virtual_hosted = self._table("orders")
        path_style = self._table("refunds", url="https://s3.eu-west-1.amazonaws.com/exports/refunds/*.csv")
        other_bucket = self._table("archive", url="https://archive.s3.eu-west-1.amazonaws.com/a.parquet")
        other_key = self._table("mirror", credential=other_credential)

        self._migrate()

        def source_of(table: DataWarehouseTable) -> ExternalDataSource:
            return self._schema_for(table).source

        assert source_of(virtual_hosted).pk == source_of(path_style).pk
        assert len({source_of(t).pk for t in (virtual_hosted, other_bucket, other_key)}) == 3
        assert ExternalDataSource.objects.filter(team=self.team).count() == 3
        assert source_of(other_bucket).job_inputs["bucket"] == "archive"
        assert source_of(other_key).job_inputs["access_key_id"] == "AKIASECOND"
        assert source_of(virtual_hosted).connection_metadata[MIGRATION_MARKER_KEY] == {
            "group_key": "s3/eu-west-1/exports",
            "credential_id": str(self.credential.pk),
        }

    def test_a_live_run_creates_a_turned_off_schema_and_starts_one_free_copy(self) -> None:
        created_at = datetime(2024, 3, 1, tzinfo=UTC)
        table = self._table(created_at=created_at)

        [outcome] = self._migrate()

        schema = self._schema_for(table)
        expected_contract = table_definition_for(
            "orders", parse_self_managed_url(EXPORTS_URL), "CSVWithNames", table.columns, True
        ).schema_metadata()
        assert outcome.action == "started"
        assert outcome.workflow_id is not None and outcome.workflow_id.startswith(
            f"{schema.id}-self-managed-migration-"
        )
        assert (schema.name, schema.should_sync, schema.sync_type) == ("orders", False, "full_refresh")
        assert schema.sync_type_config == {"schema_metadata": {**expected_contract, SCHEMA_PINNED_METADATA_KEY: True}}
        assert expected_contract["preserve_column_names"] is True
        assert schema.source.source_type == "AmazonS3"
        assert schema.source.created_at == created_at
        assert schema.source.job_inputs["region"] == "eu-west-1"
        assert ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=schema.source).exists()
        self.sync_schedule.assert_called_once_with(schema, create=True, should_sync=False, trigger_immediately=False)
        assert self.trigger.call_args.kwargs == {
            "billable": False,
            "reset_pipeline": False,
            "workflow_id_prefix": "self-managed-migration",
            "workflow_id": outcome.workflow_id,
        }
        table.refresh_from_db()
        assert (table.credential_id, table.url_pattern, table.external_data_source_id) == (
            self.credential.pk,
            EXPORTS_URL,
            None,
        )
        assert table.options["csv_allow_double_quotes"] is True
        assert table.options[MIGRATION_MARKER_KEY]["workflow_id"] == outcome.workflow_id
        assert table.options[MIGRATION_MARKER_KEY]["state"] == "triggered"

    def test_a_dry_run_writes_nothing(self) -> None:
        table = self._table()

        [outcome] = self._migrate(live_run=False)

        assert (outcome.action, outcome.status.state) == ("would_start", TableMigrationState.PENDING)
        assert not ExternalDataSource.objects.filter(team=self.team).exists()
        assert not ExternalDataSchema.objects.filter(team=self.team).exists()
        self.sync_schedule.assert_not_called()
        self.trigger.assert_not_called()
        table.refresh_from_db()
        assert MIGRATION_MARKER_KEY not in table.options

    def test_running_again_never_duplicates_or_restarts_a_copy(self) -> None:
        table = self._table()
        self._migrate()

        [waiting] = self._migrate()
        assert (waiting.action, waiting.status.reason) == ("none", "waiting for the copy to start")

        self._job(table, ExternalDataJobStatus.RUNNING)
        [running] = self._migrate()
        assert (running.action, running.status.state) == ("none", TableMigrationState.RUNNING)

        self._job(table, ExternalDataJobStatus.FAILED, latest_error="The bucket doesn't exist")
        [failed] = self._migrate()
        assert (failed.action, failed.status.state, failed.status.reason) == (
            "none",
            TableMigrationState.FAILED,
            "The bucket doesn't exist",
        )

        [retried] = self._migrate(retry_failed=True)
        assert retried.action == "retried"
        # A run that wrote a job has ended, and Temporal refuses its id, so the retry takes a new one.
        assert retried.workflow_id == self.workflow_ids[1] != self.workflow_ids[0]

        assert self.trigger_count == 2
        assert ExternalDataSchema.objects.filter(team=self.team).count() == 1
        assert ExternalDataSource.objects.filter(team=self.team).count() == 1

    def test_a_migrated_table_is_never_started_again(self) -> None:
        table = self._table()
        self._migrate()
        schema = self._schema_for(table)
        self._job(table, ExternalDataJobStatus.COMPLETED)
        table.refresh_from_db()
        table.adopt_into_source(schema.source)
        table.save()

        [outcome] = self._migrate(retry_failed=True)

        assert (outcome.action, outcome.status.state) == ("none", TableMigrationState.MIGRATED)
        assert self.trigger_count == 1

    def test_a_completed_copy_that_did_not_adopt_the_table_can_be_retried(self) -> None:
        table = self._table()
        self._migrate()
        self._job(table, ExternalDataJobStatus.COMPLETED)

        [outcome] = self._migrate(retry_failed=True)

        assert (outcome.status.state, outcome.action) == (TableMigrationState.FAILED, "retried")

    def test_a_start_that_never_wrote_a_job_is_retried_with_the_same_workflow_id(self) -> None:
        self._table()
        self._migrate()

        [outcome] = self._migrate(retry_failed=True)

        assert outcome.action == "retried"
        assert self.workflow_ids[0] == self.workflow_ids[1]

    @parameterized.expand(
        [
            ("temporal_never_got_it", None),
            ("temporal_already_runs_it", WorkflowStartError("already started")),
        ]
    )
    def test_a_crash_after_dispatch_never_starts_a_second_copy(
        self, _name: str, restart_error: WorkflowStartError | None
    ) -> None:
        table = self._table()
        self._migrate()
        # The state a command leaves when it stops after the start and before the confirmation.
        stored_id = self._marker(table)["workflow_id"]
        _update_marker(table, state="dispatching", triggered_at=None)
        if restart_error is not None:
            restart_error.__cause__ = WorkflowAlreadyStartedError(stored_id, "external-data-job")
            self.trigger.side_effect = restart_error

        [waiting] = evaluate_tables(team_id=self.team.pk, resolve_region=_no_region)
        assert waiting.reason == "a start was not confirmed; the next run starts it with the same workflow id"
        [outcome] = self._migrate()

        assert (outcome.action, outcome.workflow_id) == ("started", stored_id)
        assert self.trigger.call_args.kwargs["workflow_id"] == stored_id
        assert self._marker(table)["state"] == "triggered"
        assert ExternalDataSchema.objects.filter(team=self.team).count() == 1

    def test_a_retry_of_a_confirmed_run_that_temporal_still_holds_fails_the_start(self) -> None:
        table = self._table()
        self._migrate()
        stored_id = self._marker(table)["workflow_id"]
        error = WorkflowStartError("already started")
        error.__cause__ = WorkflowAlreadyStartedError(stored_id, "external-data-job")
        self.trigger.side_effect = error

        [outcome] = self._migrate(retry_failed=True)

        assert outcome.action == "start_failed"
        assert stored_id in (outcome.error or "")
        assert self._marker(table)["state"] == "triggered"

    @parameterized.expand(
        [
            ("schedule_rpc_error", "sync_schedule", RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")),
            ("schedule_unexpected_error", "sync_schedule", RuntimeError("boom")),
            ("trigger_unexpected_error", "trigger", RuntimeError("boom")),
        ]
    )
    def test_an_error_on_one_table_fails_only_that_start(self, _name: str, mock_name: str, error: Exception) -> None:
        self._table("first", created_at=datetime(2024, 1, 1, tzinfo=UTC))
        self._table("second", url="https://exports.s3.eu-west-1.amazonaws.com/b/*.csv")
        mock = getattr(self, mock_name)
        original = mock.side_effect
        calls = {"count": 0}

        def fail_first(*args: Any, **kwargs: Any) -> Any:
            calls["count"] += 1
            if calls["count"] == 1:
                raise error
            return original(*args, **kwargs) if original is not None else None

        mock.side_effect = fail_first

        outcomes = self._migrate()

        assert [(o.status.name, o.action) for o in outcomes] == [("first", "start_failed"), ("second", "started")]
        assert type(error).__name__ in (outcomes[0].error or "")

    @parameterized.expand(
        [
            ("unknown_host", {"url": "https://minio.example.com/exports/a.csv"}, "isn't a storage host"),
            ("unsupported_format", {"table_format": "TabSeparated"}, "has no import equivalent"),
            ("delta_with_glob", {"table_format": "Delta", "url": EXPORTS_URL}, "can't hold a file pattern"),
            (
                "azure_key_for_another_account",
                {"url": "https://examplestore.blob.core.windows.net/exports/a.csv"},
                "isn't the storage account name",
            ),
        ]
    )
    def test_a_table_that_cant_be_mapped_is_skipped_with_its_reason(
        self, _name: str, fields: dict[str, Any], reason: str
    ) -> None:
        self._table(**fields)

        [outcome] = self._migrate()

        assert outcome.status.state == TableMigrationState.SKIPPED
        assert reason in (outcome.status.reason or "")
        assert outcome.action == "none"
        assert not ExternalDataSchema.objects.filter(team=self.team).exists()

    def test_teams_without_the_flag_are_skipped(self) -> None:
        self.flag_missing.return_value = True
        self._table()

        [outcome] = self._migrate()

        assert outcome.status.state == TableMigrationState.SKIPPED
        assert "dwh-object-storage-sources" in (outcome.status.reason or "")
        self.trigger.assert_not_called()

    @parameterized.expand(
        [
            ("object_rule_restricts", True, "none", TableMigrationState.SKIPPED),
            ("object_rule_grants", True, "editor", TableMigrationState.SKIPPED),
            ("rule_on_another_table", False, "none", TableMigrationState.PENDING),
        ]
    )
    def test_a_table_with_its_own_access_rules_is_skipped(
        self, _name: str, on_this_table: bool, access_level: str, expected: TableMigrationState
    ) -> None:
        table = self._table()
        other = self._table("other", url="https://exports.s3.eu-west-1.amazonaws.com/o/*.csv")
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(table.id if on_this_table else other.id),
            access_level=access_level,
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )

        outcome = next(o for o in self._migrate() if o.status.table_id == str(table.id))

        assert outcome.status.state == expected
        if expected == TableMigrationState.SKIPPED:
            assert "own access rules" in (outcome.status.reason or "")
            assert not ExternalDataSchema.objects.filter(table=table).exists()

    @parameterized.expand([("member_rule_on_sources", True), ("default_rule_on_sources", False)])
    def test_a_project_with_access_rules_for_sources_is_skipped(self, _name: str, for_member: bool) -> None:
        table = self._table()
        AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            resource_id=None,
            access_level="none",
            organization_member=(
                OrganizationMembership.objects.get(user=self.user, organization=self.organization)
                if for_member
                else None
            ),
        )

        [outcome] = self._migrate()

        assert outcome.status.table_id == str(table.id)
        assert outcome.status.state == TableMigrationState.SKIPPED
        assert "access rules for sources" in (outcome.status.reason or "")
        assert not ExternalDataSchema.objects.filter(table=table).exists()

    def test_status_reports_every_state(self) -> None:
        pending = self._table("pending_table")
        self._table("skipped_table", url="https://minio.example.com/exports/a.csv")
        running = self._table("running_table", url="https://exports.s3.eu-west-1.amazonaws.com/r/*.csv")
        failed = self._table("failed_table", url="https://exports.s3.eu-west-1.amazonaws.com/f/*.csv")
        migrated = self._table("migrated_table", url="https://exports.s3.eu-west-1.amazonaws.com/m/*.csv")
        abandoned = self._table("abandoned_table", url="https://exports.s3.eu-west-1.amazonaws.com/a/*.csv")
        self._migrate(table_ids=tuple(str(t.id) for t in (running, failed, migrated, abandoned)))
        self._job(running, ExternalDataJobStatus.RUNNING)
        self._job(failed, ExternalDataJobStatus.FAILED)
        self._job(migrated, ExternalDataJobStatus.COMPLETED)
        migrated.refresh_from_db()
        migrated.adopt_into_source(self._schema_for(migrated).source)
        migrated.save()
        self._job(abandoned, ExternalDataJobStatus.FAILED)
        abandon_tables([str(abandoned.id)], reason="customer asked to keep it", live_run=True)

        assert self._states() == {
            pending.name: TableMigrationState.PENDING,
            "skipped_table": TableMigrationState.SKIPPED,
            running.name: TableMigrationState.RUNNING,
            failed.name: TableMigrationState.FAILED,
            migrated.name: TableMigrationState.MIGRATED,
            abandoned.name: TableMigrationState.ABANDONED,
        }

    def test_selection_ignores_synced_deleted_and_other_teams_tables(self) -> None:
        self._table("deleted_table", deleted=True)
        self._table("no_credential", credential=None)
        DataWarehouseTable.raw_objects.filter(name="no_credential").update(credential=None)
        source = ExternalDataSource.objects.create(team=self.team, source_type="Postgres", job_inputs={})
        self._table("synced_table", external_data_source=source)
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        DataWarehouseTable.objects.create(
            name="other_team_table", format="CSVWithNames", url_pattern=EXPORTS_URL, team=other_team
        )
        kept = self._table("kept")

        assert [status.table_id for status in evaluate_tables(team_id=self.team.pk)] == [str(kept.id)]

    def test_limit_and_table_ids_bound_a_run(self) -> None:
        first = self._table("first", created_at=datetime(2024, 1, 1, tzinfo=UTC))
        second = self._table(
            "second",
            url="https://exports.s3.eu-west-1.amazonaws.com/b/*.csv",
            created_at=datetime(2024, 1, 2, tzinfo=UTC),
        )
        third = self._table("third", url="https://exports.s3.eu-west-1.amazonaws.com/c/*.csv")

        outcomes = self._migrate(limit=1, table_ids=(str(second.id), str(third.id)))

        assert [(o.status.name, o.action) for o in outcomes] == [("second", "started"), ("third", "limit_reached")]
        assert not ExternalDataSchema.objects.filter(table=first).exists()

    def test_a_new_source_is_dated_to_its_oldest_table(self) -> None:
        old = datetime(2024, 1, 15, tzinfo=UTC)
        newer = self._table("newer", url="https://exports.s3.eu-west-1.amazonaws.com/n/*.csv")
        self._table("older", created_at=old)

        self._migrate()

        assert self._schema_for(newer).source.created_at == old
        assert ExternalDataSource.objects.filter(team=self.team).count() == 1

    def test_an_existing_source_keeps_its_date(self) -> None:
        newer = self._table("newer", url="https://exports.s3.eu-west-1.amazonaws.com/n/*.csv")
        self._migrate()
        source_created_at = self._schema_for(newer).source.created_at
        older = self._table("older", created_at=datetime(2024, 1, 15, tzinfo=UTC))

        self._migrate()

        assert self._schema_for(older).source.created_at == source_created_at
        assert ExternalDataSource.objects.filter(team=self.team).count() == 1

    def test_a_failed_start_keeps_the_schema_and_is_started_by_the_next_run(self) -> None:
        table = self._table()
        self.trigger.side_effect = WorkflowStartError("temporal is down")

        [failed] = self._migrate()

        assert (failed.action, failed.error) == ("start_failed", "temporal is down")
        marker = self._marker(table)
        assert marker["state"] == "dispatching"
        assert table.credential_id == self.credential.pk

        self.trigger.side_effect = self._trigger
        [started] = self._migrate()

        assert (started.action, started.workflow_id) == ("started", marker["workflow_id"])
        assert ExternalDataSchema.objects.filter(team=self.team).count() == 1

    def test_a_name_already_taken_in_the_bucket_fails_the_start(self) -> None:
        self._table("orders")
        self._migrate()
        source = ExternalDataSource.objects.get(team=self.team)
        ExternalDataSchema.objects.create(name="dupe", team=self.team, source=source)
        self._table("dupe", url="https://exports.s3.eu-west-1.amazonaws.com/d/*.csv")

        outcomes = self._migrate()

        assert [(o.status.name, o.action) for o in outcomes][-1] == ("dupe", "start_failed")

    @parameterized.expand([("named_region", "eu-west-1", "started"), ("unknown_region", None, "none")])
    def test_a_bucket_url_without_a_region_asks_s3_once_per_bucket(
        self, _name: str, region: str | None, expected_action: str
    ) -> None:
        self._table("a", url="https://exports.s3.amazonaws.com/a/*.csv")
        self._table("b", url="https://s3.amazonaws.com/exports/b/*.csv")
        resolver = MagicMock(return_value=region)

        outcomes = self._migrate(resolve_region=resolver)

        assert [o.action for o in outcomes] == [expected_action] * 2
        resolver.assert_called_once()
        if region is not None:
            assert ExternalDataSource.objects.get(team=self.team).job_inputs["region"] == region

    def test_abandon_removes_what_the_migration_made_and_keeps_the_table(self) -> None:
        table = self._table()
        self._migrate()
        self._job(table, ExternalDataJobStatus.FAILED)
        schema = self._schema_for(table)

        [outcome] = abandon_tables([str(table.id)], reason="customer asked to keep it", live_run=True)

        assert outcome.action == "abandoned"
        schema.refresh_from_db()
        assert (schema.deleted, schema.table_id) == (True, None)
        assert ExternalDataSource.objects.get(pk=schema.source_id).deleted is True
        self.delete_schedule.assert_called_once_with(str(schema.id))
        table.refresh_from_db()
        assert (table.deleted, table.credential_id, table.url_pattern) == (False, self.credential.pk, EXPORTS_URL)
        assert table.options[MIGRATION_MARKER_KEY]["reason"] == "customer asked to keep it"
        assert self._migrate()[0].status.state == TableMigrationState.ABANDONED
        assert self.trigger_count == 1

    def test_abandon_is_kept_when_the_schedule_delete_fails(self) -> None:
        table = self._table()
        self._migrate()
        self._job(table, ExternalDataJobStatus.FAILED)
        schema = self._schema_for(table)
        self.delete_schedule.side_effect = RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")

        [outcome] = abandon_tables([str(table.id)], reason="customer asked to keep it", live_run=True)

        assert outcome.action == "abandoned"
        schema.refresh_from_db()
        assert schema.deleted is True
        assert self._marker(table)["state"] == "abandoned"
        assert self._migrate(retry_failed=True)[0].status.state == TableMigrationState.ABANDONED
        assert self.trigger_count == 1

    @parameterized.expand([("confirmed", "triggered"), ("not_confirmed", "dispatching")])
    def test_abandon_refuses_a_copy_that_started_without_a_job(self, _name: str, state: str) -> None:
        table = self._table()
        self._migrate()
        _update_marker(table, state=state)

        [outcome] = abandon_tables([str(table.id)], live_run=True)

        assert outcome.action == "refused"
        assert "has no job yet" in (outcome.reason or "")
        assert ExternalDataSchema.objects.filter(table=table, deleted=False).exists()

    def test_abandon_keeps_a_source_that_holds_other_tables(self) -> None:
        table = self._table()
        other = self._table("other", url="https://exports.s3.eu-west-1.amazonaws.com/o/*.csv")
        self._migrate()
        self._job(table, ExternalDataJobStatus.FAILED)

        abandon_tables([str(table.id)], live_run=True)

        assert self._schema_for(other).source.deleted is False

    def test_abandon_of_a_table_that_was_never_planned_only_records_the_reason(self) -> None:
        table = self._table()

        [outcome] = abandon_tables([str(table.id)], reason="not wanted", live_run=True)

        assert outcome.action == "abandoned"
        assert not ExternalDataSource.objects.filter(team=self.team).exists()
        self.delete_schedule.assert_not_called()

    @parameterized.expand(
        [
            ("migrated", ExternalDataJobStatus.COMPLETED, True, "the table is already migrated"),
            ("running", ExternalDataJobStatus.RUNNING, False, "the table's copy is running"),
        ]
    )
    def test_abandon_refuses_a_table_it_cant_leave_self_managed(
        self, _name: str, job_status: str, adopt: bool, reason: str
    ) -> None:
        table = self._table()
        self._migrate()
        self._job(table, job_status)
        if adopt:
            table.refresh_from_db()
            table.adopt_into_source(self._schema_for(table).source)
            table.save()

        [outcome] = abandon_tables([str(table.id)], live_run=True)

        assert (outcome.action, outcome.reason) == ("refused", reason)
        assert ExternalDataSchema.objects.filter(table=table, deleted=False).exists()

    def test_a_dry_run_abandon_writes_nothing(self) -> None:
        table = self._table()
        self._migrate()
        self._job(table, ExternalDataJobStatus.FAILED)

        outcomes = abandon_tables([str(table.id), "00000000-0000-0000-0000-000000000000"])

        assert [o.action for o in outcomes] == ["would_abandon", "refused"]
        assert ExternalDataSchema.objects.filter(table=table, deleted=False).exists()
        self.delete_schedule.assert_not_called()

    def test_an_adopted_table_is_still_queried_by_its_bare_name(self) -> None:
        table = self._table("orders_raw")
        self._migrate()
        source = self._schema_for(table).source
        table.refresh_from_db()
        table.adopt_into_source(source)
        table.url_pattern = "https://bucket.s3.amazonaws.com/team_1/orders_raw"
        table.format = DataWarehouseTableFormat.DeltaS3Wrapper
        table.save(internally_computed_url_pattern=True)

        database = Database.create_for(team=self.team)

        assert database.has_table("orders_raw")
        assert database.has_table("amazons3.orders_raw")


class TestMigrateSelfManagedTablesCommand(BaseTest):
    @parameterized.expand(
        [
            ("zero_limit", {"limit": 0}, "--limit"),
            ("negative_sleep", {"sleep_seconds": -1}, "--sleep-seconds"),
            ("status_and_abandon", {"status": True, "abandon": "x"}, "only one"),
            ("empty_abandon", {"abandon": " , "}, "at least one table id"),
        ]
    )
    def test_rejects_invalid_options(self, _name: str, options: dict[str, Any], message: str) -> None:
        with self.assertRaisesRegex(CommandError, message):
            call_command("migrate_self_managed_tables", **options)

    def test_status_and_dry_run_report_each_table_and_change_nothing(self) -> None:
        DataWarehouseTable.objects.create(
            name="orders",
            format="CSVWithNames",
            url_pattern="https://minio.example.com/exports/a.csv",
            team=self.team,
            credential=DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=self.team),
        )

        for options in ({"status": True}, {}):
            out = StringIO()
            call_command("migrate_self_managed_tables", team_id=self.team.pk, stdout=out, **options)
            assert "name=orders state=skipped" in out.getvalue()

        assert not ExternalDataSource.objects.filter(team=self.team).exists()


class TestDeletingAMigrationSchema(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        patches = [
            patch(f"{SOURCE_VIEWS}.base.bulk_delete_external_data_schedules", return_value=[]),
            patch(f"{SOURCE_VIEWS}.base.delete_external_data_schedule"),
            patch(f"{SOURCE_VIEWS}.base.delete_discover_schemas_schedule"),
            patch("products.data_warehouse.backend.s3.get_s3_client"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="AmazonS3",
            job_inputs={},
            connection_metadata={MIGRATION_MARKER_KEY: {"group_key": "s3/eu-west-1/exports", "credential_id": "c"}},
        )
        self.credential = DataWarehouseCredential.objects.create(
            access_key="AKIAFIRST", access_secret="c2VjcmV0", team=self.team
        )

    def _linked_table(self, adopted: bool) -> tuple[DataWarehouseTable, ExternalDataSchema]:
        table = DataWarehouseTable.objects.create(
            name="orders",
            format=DataWarehouseTableFormat.CSVWithNames,
            url_pattern=EXPORTS_URL,
            team=self.team,
            credential=None if adopted else self.credential,
            external_data_source=self.source if adopted else None,
            options={MIGRATION_MARKER_KEY: {"state": "triggered", "workflow_id": "workflow-1"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="orders", team=self.team, source=self.source, table=table, should_sync=False
        )
        return table, schema

    def _delete(self, path: str, schema: ExternalDataSchema) -> None:
        urls = {
            "source": f"/api/environments/{self.team.pk}/external_data_sources/{self.source.pk}",
            "schema": f"/api/environments/{self.team.pk}/external_data_schemas/{schema.pk}",
            "schema_data": f"/api/environments/{self.team.pk}/external_data_schemas/{schema.pk}/delete_data",
        }
        response = self.client.delete(urls[path])
        assert response.status_code in (200, 204), response.content

    @parameterized.expand([("source",), ("schema",), ("schema_data",)])
    def test_a_table_that_is_not_adopted_yet_stays_self_managed(self, path: str) -> None:
        table, schema = self._linked_table(adopted=False)

        self._delete(path, schema)

        table.refresh_from_db()
        schema.refresh_from_db()
        assert (table.deleted, table.credential_id, table.url_pattern) == (False, self.credential.pk, EXPORTS_URL)
        assert schema.table_id is None
        assert table.options[MIGRATION_MARKER_KEY]["state"] == "abandoned"
        [status] = evaluate_tables(team_id=self.team.pk, resolve_region=_no_region)
        assert status.state == TableMigrationState.ABANDONED

    @parameterized.expand([("source",), ("schema",), ("schema_data",)])
    def test_an_adopted_table_is_deleted_as_before(self, path: str) -> None:
        table, schema = self._linked_table(adopted=True)

        self._delete(path, schema)

        assert DataWarehouseTable.raw_objects.get(pk=table.pk).deleted is True
