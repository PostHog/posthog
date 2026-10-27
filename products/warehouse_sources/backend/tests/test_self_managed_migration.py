from datetime import UTC, datetime
from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from posthog.hogql.database.database import Database

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataSourceDestination
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_PINNED_METADATA_KEY,
    SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY,
    ExternalDataSchema,
    self_managed_table_ref,
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
SCHEMA_VIEWS = "products.warehouse_sources.backend.presentation.views.external_data_schema"
EXPORTS_URL = "https://exports.s3.eu-west-1.amazonaws.com/orders/*.csv"


def _no_region(_bucket: str, _credential: SelfManagedCredential) -> str | None:
    raise AssertionError("every URL in this test names its region")


def _schemas_for(table: DataWarehouseTable) -> list[ExternalDataSchema]:
    return [
        schema
        for schema in ExternalDataSchema.objects.select_related("source").filter(team_id=table.team_id)
        if (ref := self_managed_table_ref(schema)) is not None and ref.table_id == str(table.id)
    ]


def _schema_for(table: DataWarehouseTable) -> ExternalDataSchema:
    [schema] = [schema for schema in _schemas_for(table) if not schema.deleted]
    return schema


class _MigrationTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        patches = [
            patch(f"{MODULE}.source_feature_flag_missing", return_value=False),
            patch(f"{MODULE}.delete_external_data_schedule"),
            # The location check resolves the bucket host, and these example buckets don't exist.
            patch.object(source_base, "validate_warehouse_table_url_pattern", return_value=(True, "")),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.flag_missing, self.delete_schedule, _ = mocks
        self.credential = self._credential("AKIAFIRST")

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
            MigrationOptions(team_id=self.team.pk, live_run=live_run, **options), resolve_region=resolve_region
        )

    def _abandon(self, table: DataWarehouseTable, **options: Any) -> Any:
        options.setdefault("live_run", True)
        [outcome] = abandon_tables([str(table.id)], resolve_region=_no_region, **options)
        return outcome

    def _status(self, table: DataWarehouseTable) -> Any:
        [status] = evaluate_tables(team_id=self.team.pk, table_ids=[str(table.id)], resolve_region=_no_region)
        return status

    def _job(self, table: DataWarehouseTable, status: str, latest_error: str | None = None) -> ExternalDataJob:
        schema = _schema_for(table)
        return ExternalDataJob.objects.create(
            team=self.team, pipeline=schema.source, schema=schema, status=status, latest_error=latest_error
        )

    def _adopt(self, table: DataWarehouseTable) -> None:
        schema = _schema_for(table)
        table.refresh_from_db()
        table.adopt_into_source(schema.source)
        table.url_pattern = f"https://bucket.s3.amazonaws.com/team_{self.team.pk}/{table.name}"
        table.format = DataWarehouseTableFormat.DeltaS3Wrapper
        table.save(internally_computed_url_pattern=True)
        schema.table = table
        schema.save()


class TestSelfManagedMigration(_MigrationTest):
    def test_tables_group_into_one_source_per_credential_and_bucket(self) -> None:
        other_credential = self._credential("AKIASECOND")
        virtual_hosted = self._table("orders")
        path_style = self._table("refunds", url="https://s3.eu-west-1.amazonaws.com/exports/refunds/*.csv")
        other_bucket = self._table("archive", url="https://archive.s3.eu-west-1.amazonaws.com/a.parquet")
        other_key = self._table("mirror", credential=other_credential)

        self._migrate()

        def source_of(table: DataWarehouseTable) -> ExternalDataSource:
            return _schema_for(table).source

        assert source_of(virtual_hosted).pk == source_of(path_style).pk
        assert len({source_of(t).pk for t in (virtual_hosted, other_bucket, other_key)}) == 3
        assert ExternalDataSource.objects.filter(team=self.team).count() == 3
        # Two sources of one type can't both go without a prefix, or their table names would clash.
        prefixes = [source_of(t).prefix or "" for t in (virtual_hosted, other_bucket, other_key)]
        assert prefixes.count("") == 1 and len(set(prefixes)) == 3
        assert set(prefixes) - {""} <= {"exports", "archive"}
        assert source_of(other_bucket).job_inputs["url_pattern"] == "https://s3.eu-west-1.amazonaws.com/archive/"
        assert source_of(other_key).job_inputs["access_key_id"] == "AKIASECOND"
        assert (source_of(virtual_hosted).connection_metadata or {})[MIGRATION_MARKER_KEY] == {
            "group_key": "s3/eu-west-1/exports",
            "credential_id": str(self.credential.pk),
        }

    def test_a_live_run_creates_a_turned_off_schema_and_changes_nothing_else(self) -> None:
        created_at = datetime(2024, 3, 1, tzinfo=UTC)
        table = self._table(created_at=created_at)
        before = DataWarehouseTable.raw_objects.values().get(pk=table.pk)

        [outcome] = self._migrate()

        schema = _schema_for(table)
        expected_contract = table_definition_for(
            "orders", parse_self_managed_url(EXPORTS_URL), "CSVWithNames", table.columns, True
        ).schema_metadata()
        assert (outcome.action, outcome.status.state) == ("linked", TableMigrationState.AWAITING_SYNC)
        assert (schema.name, schema.should_sync, schema.sync_type, schema.table_id) == (
            "orders",
            False,
            "full_refresh",
            None,
        )
        assert schema.sync_type_config == {
            "schema_metadata": {
                **expected_contract,
                SCHEMA_PINNED_METADATA_KEY: True,
                SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY: {
                    "table_id": str(table.id),
                    "url_pattern": EXPORTS_URL,
                    "format": "CSVWithNames",
                },
            }
        }
        assert expected_contract["preserve_column_names"] is True
        assert schema.source.source_type == "AmazonS3"
        # A normal new source: its date is not moved to the table's.
        assert schema.source.created_at > created_at
        assert schema.source.job_inputs["url_pattern"] == "https://s3.eu-west-1.amazonaws.com/exports/"
        assert ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=schema.source).exists()
        assert not ExternalDataJob.objects.filter(team=self.team).exists()
        assert DataWarehouseTable.raw_objects.values().get(pk=table.pk) == before

    def test_a_dry_run_writes_nothing(self) -> None:
        self._table()

        [outcome] = self._migrate(live_run=False)

        assert (outcome.action, outcome.status.state) == ("would_link", TableMigrationState.PENDING)
        assert not ExternalDataSource.objects.filter(team=self.team).exists()
        assert not ExternalDataSchema.objects.filter(team=self.team).exists()

    def test_running_again_changes_nothing(self) -> None:
        table = self._table()
        self._migrate()

        [again] = self._migrate()

        assert (again.action, again.status.state) == ("none", TableMigrationState.AWAITING_SYNC)
        assert again.status.schema_id == str(_schema_for(table).id)
        assert ExternalDataSchema.objects.filter(team=self.team).count() == 1
        assert ExternalDataSource.objects.filter(team=self.team).count() == 1

    @parameterized.expand(
        [
            ("syncing_off", False, None, None, {}, "syncing is off"),
            ("syncing_on", True, None, None, {}, "syncing is on; waiting for the first sync"),
            ("first_sync_running", True, ExternalDataJobStatus.RUNNING, None, {}, "the first sync is running"),
            (
                "first_sync_failed",
                True,
                ExternalDataJobStatus.FAILED,
                "The bucket doesn't exist",
                {},
                "The bucket doesn't exist; the table still reads its own bucket",
            ),
            (
                "table_edited",
                False,
                None,
                None,
                {"url_pattern": "https://exports.s3.eu-west-1.amazonaws.com/new/*.csv"},
                "the table changed after the migration, so a sync makes a separate table",
            ),
        ]
    )
    def test_a_linked_table_reports_why_it_still_reads_its_own_bucket(
        self,
        _name: str,
        should_sync: bool,
        job_status: str | None,
        latest_error: str | None,
        table_change: dict[str, Any],
        reason: str,
    ) -> None:
        table = self._table()
        self._migrate()
        ExternalDataSchema.objects.filter(pk=_schema_for(table).pk).update(should_sync=should_sync)
        if job_status is not None:
            self._job(table, job_status, latest_error=latest_error)
        if table_change:
            DataWarehouseTable.raw_objects.filter(pk=table.pk).update(**table_change)

        status = self._status(table)

        assert (status.state, status.reason) == (TableMigrationState.AWAITING_SYNC, reason)
        table.refresh_from_db()
        assert (table.external_data_source_id, table.credential_id) == (None, self.credential.pk)

    def test_a_schema_that_synced_a_separate_table_is_reported(self) -> None:
        table = self._table()
        self._migrate()
        schema = _schema_for(table)
        schema.table = DataWarehouseTable.objects.create(
            name="amazons3_orders", format="Parquet", team=self.team, external_data_source=schema.source
        )
        schema.save()

        status = self._status(table)

        assert (status.state, status.reason) == (
            TableMigrationState.AWAITING_SYNC,
            "the table changed after the migration, so its schema syncs a separate table",
        )

    def test_a_migrated_table_is_never_linked_again(self) -> None:
        table = self._table()
        self._migrate()
        self._adopt(table)

        [outcome] = self._migrate()

        assert (outcome.action, outcome.status.state) == ("none", TableMigrationState.MIGRATED)
        assert ExternalDataSchema.objects.filter(team=self.team).count() == 1

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
        assert not ExternalDataSchema.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("object_rule_restricts", True, "none", TableMigrationState.SKIPPED),
            ("object_rule_grants", True, "editor", TableMigrationState.SKIPPED),
            ("rule_on_another_table", False, "none", TableMigrationState.AWAITING_SYNC),
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
            assert _schemas_for(table) == []

    @parameterized.expand(
        [
            ("member_rule_on_sources", "external_data_source", True),
            ("default_rule_on_sources", "external_data_source", False),
            ("member_rule_on_the_warehouse", "warehouse_objects", True),
            ("default_rule_on_the_warehouse", "warehouse_objects", False),
        ]
    )
    def test_a_project_with_access_rules_for_sources_is_skipped(
        self, _name: str, resource: str, for_member: bool
    ) -> None:
        table = self._table()
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
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
        assert _schemas_for(table) == []

    def test_status_reports_every_state(self) -> None:
        pending = self._table("pending_table")
        self._table("skipped_table", url="https://minio.example.com/exports/a.csv")
        awaiting = self._table("awaiting_table", url="https://exports.s3.eu-west-1.amazonaws.com/w/*.csv")
        migrated = self._table("migrated_table", url="https://exports.s3.eu-west-1.amazonaws.com/m/*.csv")
        abandoned = self._table("abandoned_table", url="https://exports.s3.eu-west-1.amazonaws.com/a/*.csv")
        self._migrate(table_ids=tuple(str(t.id) for t in (awaiting, migrated, abandoned)))
        self._adopt(migrated)
        self._abandon(abandoned, reason="customer asked to keep it")

        statuses = evaluate_tables(team_id=self.team.pk, resolve_region=_no_region)

        assert {status.name: status.state for status in statuses} == {
            pending.name: TableMigrationState.PENDING,
            "skipped_table": TableMigrationState.SKIPPED,
            awaiting.name: TableMigrationState.AWAITING_SYNC,
            migrated.name: TableMigrationState.MIGRATED,
            abandoned.name: TableMigrationState.ABANDONED,
        }
        assert next(s for s in statuses if s.name == abandoned.name).reason == "customer asked to keep it"

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

        assert [(o.status.name, o.action) for o in outcomes] == [("second", "linked"), ("third", "limit_reached")]
        assert _schemas_for(first) == []

    def test_a_name_already_taken_in_the_bucket_fails_the_link_of_that_table_only(self) -> None:
        self._table("orders")
        self._migrate()
        source = ExternalDataSource.objects.get(team=self.team)
        ExternalDataSchema.objects.create(name="dupe", team=self.team, source=source)
        self._table("dupe", url="https://exports.s3.eu-west-1.amazonaws.com/d/*.csv")
        self._table("fine", url="https://exports.s3.eu-west-1.amazonaws.com/f/*.csv")

        outcomes = self._migrate()

        assert [(o.status.name, o.action) for o in outcomes][1:] == [("dupe", "link_failed"), ("fine", "linked")]
        assert "already uses the name 'dupe'" in (outcomes[1].error or "")

    @parameterized.expand([("named_region", "eu-west-1", "linked"), ("unknown_region", None, "none")])
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
            job_inputs = ExternalDataSource.objects.get(team=self.team).job_inputs
            assert job_inputs["url_pattern"] == f"https://s3.{region}.amazonaws.com/exports/"

    def test_an_adopted_table_is_queried_by_its_bare_name_before_and_after(self) -> None:
        table = self._table("orders_raw")
        self._migrate()

        before = Database.create_for(team=self.team)
        assert before.has_table("orders_raw")
        assert not before.has_table("amazons3.orders_raw")

        self._adopt(table)

        after = Database.create_for(team=self.team)
        assert after.has_table("orders_raw")
        assert after.has_table("amazons3.orders_raw")


class TestAbandon(_MigrationTest):
    def test_abandon_removes_the_schema_and_keeps_the_table(self) -> None:
        table = self._table()
        self._migrate()
        self._job(table, ExternalDataJobStatus.FAILED)
        schema = _schema_for(table)

        outcome = self._abandon(table, reason="customer asked to keep it")

        assert outcome.action == "abandoned"
        schema.refresh_from_db()
        assert schema.deleted is True
        ref = self_managed_table_ref(schema)
        assert ref is not None and ref.abandon_reason == "customer asked to keep it"
        assert ExternalDataSource.objects.get(pk=schema.source_id).deleted is True
        self.delete_schedule.assert_called_once_with(str(schema.id))
        table.refresh_from_db()
        assert (table.deleted, table.credential_id, table.url_pattern) == (False, self.credential.pk, EXPORTS_URL)
        [again] = self._migrate()
        assert (again.action, again.status.state) == ("none", TableMigrationState.ABANDONED)
        assert ExternalDataSchema.objects.filter(team=self.team, deleted=False).count() == 0

    def test_abandon_is_kept_when_the_schedule_delete_fails(self) -> None:
        table = self._table()
        self._migrate()
        self.delete_schedule.side_effect = RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")

        assert self._abandon(table).action == "abandoned"
        assert self._status(table).state == TableMigrationState.ABANDONED

    def test_abandon_keeps_a_source_that_holds_other_tables(self) -> None:
        table = self._table()
        other = self._table("other", url="https://exports.s3.eu-west-1.amazonaws.com/o/*.csv")
        self._migrate()

        self._abandon(table)

        assert _schema_for(other).source.deleted is False

    def test_abandon_of_a_table_that_was_never_linked_records_it_and_removes_the_new_source(self) -> None:
        table = self._table()

        outcome = self._abandon(table, reason="not wanted")

        assert outcome.action == "abandoned"
        [schema] = _schemas_for(table)
        assert (schema.deleted, schema.source.deleted) == (True, True)
        self.delete_schedule.assert_not_called()
        assert (self._status(table).state, self._status(table).reason) == (TableMigrationState.ABANDONED, "not wanted")
        assert self._migrate()[0].action == "none"

    @parameterized.expand(
        [
            ("migrated", "the table is already migrated"),
            ("abandoned", "the table's migration is already abandoned"),
            ("syncing_on", "the user turned syncing on for the table's schema"),
            ("running", "the table's first sync is running"),
            ("separate_table", "the table's schema syncs a separate table"),
        ]
    )
    def test_abandon_refuses_a_table_it_must_not_touch(self, case: str, reason: str) -> None:
        table = self._table()
        self._migrate()
        schema = _schema_for(table)
        if case == "migrated":
            self._adopt(table)
        elif case == "abandoned":
            self._abandon(table)
        elif case == "syncing_on":
            ExternalDataSchema.objects.filter(pk=schema.pk).update(should_sync=True)
        elif case == "running":
            self._job(table, ExternalDataJobStatus.RUNNING)
        else:
            schema.table = DataWarehouseTable.objects.create(
                name="amazons3_orders", format="Parquet", team=self.team, external_data_source=schema.source
            )
            schema.save()
        deleted_before = ExternalDataSchema.objects.get(pk=schema.pk).deleted

        outcome = self._abandon(table)

        assert (outcome.action, outcome.reason) == ("refused", reason)
        assert ExternalDataSchema.objects.get(pk=schema.pk).deleted is deleted_before

    def test_abandon_refuses_a_table_that_cant_be_migrated(self) -> None:
        table = self._table(url="https://minio.example.com/exports/a.csv")

        outcome = self._abandon(table)

        assert outcome.action == "refused"
        assert "can't be migrated" in (outcome.reason or "")
        assert not ExternalDataSource.objects.filter(team=self.team).exists()

    def test_a_dry_run_abandon_writes_nothing(self) -> None:
        table = self._table()
        self._migrate()

        outcomes = abandon_tables(
            [str(table.id), "00000000-0000-0000-0000-000000000000"], resolve_region=_no_region, live_run=False
        )

        assert [o.action for o in outcomes] == ["would_abandon", "refused"]
        assert _schema_for(table).deleted is False
        self.delete_schedule.assert_not_called()


class TestMigrateSelfManagedTablesCommand(BaseTest):
    @parameterized.expand(
        [
            ("zero_limit", {"limit": 0}, "--limit"),
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
            patch(f"{MODULE}.source_feature_flag_missing", return_value=False),
            patch.object(source_base, "validate_warehouse_table_url_pattern", return_value=(True, "")),
            patch(f"{SOURCE_VIEWS}.base.bulk_delete_external_data_schedules", return_value=[]),
            patch(f"{SOURCE_VIEWS}.base.delete_external_data_schedule"),
            patch(f"{SOURCE_VIEWS}.base.delete_discover_schemas_schedule"),
            patch(f"{SCHEMA_VIEWS}.external_data_workflow_exists", return_value=False),
            patch("products.data_warehouse.backend.s3.get_s3_client"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.credential = DataWarehouseCredential.objects.create(
            access_key="AKIAFIRST", access_secret="c2VjcmV0", team=self.team
        )

    @parameterized.expand([("source",), ("schema",), ("schema_data",)])
    def test_deleting_before_the_first_sync_keeps_the_table_and_ends_its_migration(self, path: str) -> None:
        table = DataWarehouseTable.objects.create(
            name="orders",
            format=DataWarehouseTableFormat.CSVWithNames,
            url_pattern=EXPORTS_URL,
            team=self.team,
            credential=self.credential,
        )
        migrate_self_managed_tables(MigrationOptions(team_id=self.team.pk, live_run=True), resolve_region=_no_region)
        schema = _schema_for(table)
        urls = {
            "source": f"/api/environments/{self.team.pk}/external_data_sources/{schema.source_id}",
            "schema": f"/api/environments/{self.team.pk}/external_data_schemas/{schema.pk}",
            "schema_data": f"/api/environments/{self.team.pk}/external_data_schemas/{schema.pk}/delete_data",
        }

        response = self.client.delete(urls[path])

        assert response.status_code in (200, 204), response.content
        table.refresh_from_db()
        assert (table.deleted, table.credential_id, table.url_pattern) == (False, self.credential.pk, EXPORTS_URL)
        [status] = evaluate_tables(team_id=self.team.pk, resolve_region=_no_region)
        expected = TableMigrationState.AWAITING_SYNC if path == "schema_data" else TableMigrationState.ABANDONED
        assert status.state == expected
        assert Database.create_for(team=self.team).has_table("orders")


UPLOAD_DOMAIN = "warehouse.example.com"
UPLOAD_BUCKET = "ph-warehouse"
UPLOAD_ID = "11111111-2222-4333-8444-555555555555"


@override_settings(DATAWAREHOUSE_BUCKET=UPLOAD_BUCKET, DATAWAREHOUSE_BUCKET_DOMAIN=UPLOAD_DOMAIN)
class TestUploadedTableMigration(_MigrationTest):
    def _url(self, key: str) -> str:
        return f"https://{UPLOAD_DOMAIN}/{key.format(team=self.team.pk, upload=UPLOAD_ID)}"

    def _uploaded(
        self, name: str, key: str, table_format: str = DataWarehouseTableFormat.CSVWithNames
    ) -> DataWarehouseTable:
        table = self._table(name, url=self._url(key), table_format=table_format)
        DataWarehouseTable.raw_objects.filter(pk=table.pk).update(
            credential=None, options={"csv_allow_double_quotes": False}
        )
        table.refresh_from_db()
        return table

    @parameterized.expand(
        [
            ("file_upload_folder", "file_uploads/team_{team}/{upload}/orders.csv"),
            ("legacy_managed_folder", "managed/team_{team}/orders.csv"),
        ]
    )
    def test_an_uploaded_table_gets_a_file_upload_source_that_waits_for_the_next_upload(
        self, _name: str, key: str
    ) -> None:
        table = self._uploaded("orders", key)
        other = self._uploaded("refunds", key.replace("orders.csv", "refunds.csv"))
        before = DataWarehouseTable.raw_objects.values().get(pk=table.pk)

        outcomes = self._migrate()
        [again] = self._migrate(table_ids=(str(table.id),))

        assert [(outcome.action, outcome.status.reason) for outcome in outcomes] == [
            ("linked", "waiting for the next upload of the file")
        ] * 2
        assert (again.action, again.status.state) == ("none", TableMigrationState.AWAITING_SYNC)
        schema = _schema_for(table)
        source = schema.source
        assert source.source_type == "FileUpload"
        assert source.pk != _schema_for(other).source.pk
        assert ExternalDataSource.objects.filter(team=self.team).count() == 2
        assert source.connection_metadata == {MIGRATION_MARKER_KEY: {"group_key": f"upload/{table.pk}"}}
        # The source reads no file, so nothing can sync it before the next upload.
        assert source.job_inputs == {"upload_id": "", "filename": "", "file_format": "csv", "schema_name": "orders"}
        assert (schema.name, schema.should_sync, schema.sync_type, schema.table_id) == (
            "orders",
            False,
            "full_refresh",
            None,
        )
        assert schema.schema_metadata is not None
        assert schema.schema_metadata["preserve_column_names"] is True
        assert schema.schema_metadata["csv"] == {
            "has_header": True,
            "allow_double_quotes": False,
            "column_types": {"Order ID": "integer"},
        }
        assert schema.schema_metadata[SCHEMA_PINNED_METADATA_KEY] is True
        assert schema.schema_metadata[SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY] == {
            "table_id": str(table.id),
            "url_pattern": self._url(key),
            "format": "CSVWithNames",
        }
        assert not ExternalDataJob.objects.filter(team=self.team).exists()
        assert DataWarehouseTable.raw_objects.values().get(pk=table.pk) == before

    @parameterized.expand(
        [
            ("csv_without_a_header", DataWarehouseTableFormat.CSV, None, "has no import equivalent"),
            ("delta", DataWarehouseTableFormat.Delta, None, "has no import equivalent"),
            (
                "nested_columns",
                DataWarehouseTableFormat.Parquet,
                {"tags": {"clickhouse": "Array(Nullable(String))", "hogql": "StringArrayDatabaseField"}},
                "'tags' is a Array",
            ),
            (
                "json_dates",
                DataWarehouseTableFormat.JSON,
                {"day": {"clickhouse": "Nullable(Date)", "hogql": "DateDatabaseField"}},
                "'day' is a Date",
            ),
            (
                "padded_csv_header",
                DataWarehouseTableFormat.CSVWithNames,
                {" id ": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"}},
                "spaces around its name",
            ),
            (
                "file_metadata_column",
                DataWarehouseTableFormat.Parquet,
                {"_file_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"}},
                "a column the import adds",
            ),
        ]
    )
    def test_an_uploaded_table_the_source_cant_read_is_skipped(
        self, _name: str, table_format: str, columns: dict[str, Any] | None, reason: str
    ) -> None:
        table = self._uploaded("orders", "managed/team_{team}/orders.csv", table_format=table_format)
        if columns is not None:
            DataWarehouseTable.raw_objects.filter(pk=table.pk).update(columns=columns)

        [outcome] = self._migrate()

        assert outcome.status.state == TableMigrationState.SKIPPED
        assert reason in (outcome.status.reason or "")
        assert not ExternalDataSource.objects.filter(team=self.team).exists()

    def test_teams_without_the_flag_keep_their_uploaded_tables(self) -> None:
        self.flag_missing.return_value = True
        self._uploaded("orders", "file_uploads/team_{team}/{upload}/orders.csv")

        [outcome] = self._migrate()

        assert outcome.status.state == TableMigrationState.SKIPPED
        assert "dwh-object-storage-sources" in (outcome.status.reason or "")
        assert not ExternalDataSource.objects.filter(team=self.team).exists()

    def test_selection_takes_only_the_teams_own_uploaded_tables(self) -> None:
        self._uploaded("uploaded", "file_uploads/team_{team}/{upload}/orders.csv")
        self._uploaded("legacy", "managed/team_{team}/orders.csv")
        self._uploaded("materialized_view", "dlt/team_{team}_model_abc/modeling/orders")
        self._uploaded("another_teams_file", "managed/team_999999/orders.csv")
        self._uploaded("nested_key", "managed/team_{team}/sub/orders.csv")
        # A table made with the flag on links to its own file upload source and waits for its first sync.
        waiting = self._uploaded("waiting", "file_uploads/team_{team}/{upload}/waiting.csv")
        upload_source = ExternalDataSource.objects.create(team=self.team, source_type="FileUpload", job_inputs={})
        ExternalDataSchema.objects.create(name="waiting", team=self.team, source=upload_source, table=waiting)

        statuses = evaluate_tables(team_id=self.team.pk, resolve_region=_no_region)

        assert {status.name: status.state for status in statuses} == {
            "uploaded": TableMigrationState.PENDING,
            "legacy": TableMigrationState.PENDING,
            # Inside the team folder but not one upload, so it is listed and never planned.
            "nested_key": TableMigrationState.SKIPPED,
        }
