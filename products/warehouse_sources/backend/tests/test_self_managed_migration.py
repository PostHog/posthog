import json
import uuid
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from botocore.exceptions import BotoCoreError
from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from posthog.hogql.database.database import Database

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.access_control.backend.facade.testing import add_role_member, create_access_control, create_role
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
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
from products.warehouse_sources.backend.self_managed_access import (
    ADOPTION_ACCESS_ERROR,
    AdoptionAccessError,
    TeamAccessRules,
    assert_adoption_keeps_access,
)
from products.warehouse_sources.backend.self_managed_migration import (
    MIGRATION_MARKER_KEY,
    MigrationOptions,
    TableMigrationState,
    abandon_tables,
    backdate_migration_sources,
    evaluate_tables,
    merge_duplicate_sources,
    migrate_self_managed_tables,
    resolve_s3_bucket_region,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store import source_base
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    parse_self_managed_url,
    table_definition_for,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    self_managed_adoption_error,
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


class TestResolveS3BucketRegion:
    @parameterized.expand(
        [
            ("keyed_region", "key", "eu-west-1", "us-east-1", "eu-west-1", True, False),
            ("missing_header", "key", None, "eu-west-1", "eu-west-1", True, True),
            ("empty_key", "", None, "eu-west-1", "eu-west-1", False, True),
            ("anonymous_error", "key", None, ObjectStorageError("no region"), None, True, True),
            ("keyed_error", "key", BotoCoreError(), "eu-west-1", "eu-west-1", True, True),
        ]
    )
    def test_resolves_bucket_region(
        self,
        _name: str,
        access_key: str,
        keyed_result: str | BotoCoreError | None,
        anonymous_result: str | ObjectStorageError,
        expected_region: str | None,
        keyed_called: bool,
        anonymous_called: bool,
    ) -> None:
        credential = SelfManagedCredential(access_key=access_key, access_secret="secret")
        with patch(f"{MODULE}.boto3.client") as mock_client, patch(f"{MODULE}.lookup_s3_bucket_region") as mock_lookup:
            if isinstance(keyed_result, BotoCoreError):
                mock_client.return_value.head_bucket.side_effect = keyed_result
            else:
                headers = {"x-amz-bucket-region": keyed_result} if keyed_result is not None else {}
                mock_client.return_value.head_bucket.return_value = {"ResponseMetadata": {"HTTPHeaders": headers}}
            if isinstance(anonymous_result, ObjectStorageError):
                mock_lookup.side_effect = anonymous_result
            else:
                mock_lookup.return_value = anonymous_result

            assert resolve_s3_bucket_region("exports", credential) == expected_region

            if keyed_called:
                mock_client.assert_called_once()
                mock_client.return_value.head_bucket.assert_called_once_with(Bucket="exports")
            else:
                mock_client.assert_not_called()
            if anonymous_called:
                mock_lookup.assert_called_once_with("exports")
            else:
                mock_lookup.assert_not_called()


class _MigrationTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        patches = [
            patch(f"{MODULE}.delete_external_data_schedule"),
            # The location check resolves the bucket host, and these example buckets don't exist.
            patch.object(source_base, "validate_warehouse_table_url_pattern", return_value=(True, "")),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.delete_schedule, _ = mocks
        self.credential = self._credential("AKIAFIRST")

    def _credential(self, access_key: str, access_secret: str = "c2VjcmV0") -> DataWarehouseCredential:
        return DataWarehouseCredential.objects.create(
            access_key=access_key, access_secret=access_secret, team=self.team
        )

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
        assert (
            SourceInputsStore.load(source_of(other_bucket))["url_pattern"]
            == "https://s3.eu-west-1.amazonaws.com/archive/"
        )
        assert SourceInputsStore.load(source_of(other_key))["access_key_id"] == "AKIASECOND"
        marker = (source_of(virtual_hosted).connection_metadata or {})[MIGRATION_MARKER_KEY]
        assert marker["group_key"] == "s3/eu-west-1/exports"
        assert marker["credential_id"] == str(self.credential.pk)
        assert len(marker["credential_fingerprint"]) == 64
        assert "AKIAFIRST" not in json.dumps(marker) and "c2VjcmV0" not in json.dumps(marker)

    @parameterized.expand(
        [
            ("same_credential_row", None, True),
            ("equal_valued_credential_row", ("AKIAFIRST", "c2VjcmV0"), True),
            ("equal_after_trimming_whitespace", (" AKIAFIRST", "c2VjcmV0 "), True),
            ("different_secret", ("AKIAFIRST", "b3RoZXI="), False),
            ("different_key", ("AKIASECOND", "c2VjcmV0"), False),
        ]
    )
    def test_tables_in_one_bucket_share_a_source_when_their_credentials_hold_the_same_key(
        self, _name: str, second_credential: tuple[str, str] | None, shared: bool
    ) -> None:
        first = self._table("orders")
        second = self._table(
            "refunds",
            url="https://exports.s3.eu-west-1.amazonaws.com/refunds/*.csv",
            credential=self._credential(*second_credential) if second_credential else None,
        )

        outcomes = self._migrate()

        assert [o.action for o in outcomes] == ["linked", "linked"]
        assert (_schema_for(first).source_id == _schema_for(second).source_id) is shared
        assert ExternalDataSource.objects.filter(team=self.team).count() == (1 if shared else 2)

    @parameterized.expand([("older_first", False), ("newer_first", True)])
    def test_shared_source_uses_its_oldest_table_date_in_either_link_order(self, _name: str, newer_first: bool) -> None:
        older_date = datetime(2024, 1, 1, tzinfo=UTC)
        newer_date = datetime(2024, 2, 1, tzinfo=UTC)
        older = self._table("orders", created_at=older_date)
        newer = self._table(
            "refunds", url="https://exports.s3.eu-west-1.amazonaws.com/refunds/*.csv", created_at=newer_date
        )

        for table in (newer, older) if newer_first else (older, newer):
            [outcome] = self._migrate(table_ids=(str(table.pk),))
            assert outcome.action == "linked"

        older_schema = _schema_for(older)
        newer_schema = _schema_for(newer)
        assert older_schema.source_id == newer_schema.source_id
        assert ExternalDataSource.objects.get(pk=older_schema.source_id).created_at == older_date
        assert older_schema.created_at == older_date
        assert newer_schema.created_at == newer_date

    def test_a_newer_table_does_not_move_its_source_date_forward(self) -> None:
        older_date = datetime(2024, 1, 1, tzinfo=UTC)
        newer_date = datetime(2025, 1, 1, tzinfo=UTC)
        older = self._table("orders", created_at=older_date)
        self._migrate()
        source_id = _schema_for(older).source_id
        newer = self._table(
            "refunds", url="https://exports.s3.eu-west-1.amazonaws.com/refunds/*.csv", created_at=newer_date
        )

        self._migrate(table_ids=(str(newer.pk),))

        assert ExternalDataSource.objects.get(pk=source_id).created_at == older_date
        assert _schema_for(newer).created_at == newer_date

    @parameterized.expand(
        [
            ("same_value", "c2VjcmV0", False, True),
            ("different_value", "b3RoZXI=", False, False),
            ("credential_row_gone", "c2VjcmV0", True, False),
        ]
    )
    def test_a_source_with_a_credential_id_marker_takes_tables_whose_credential_holds_its_key(
        self, _name: str, secret: str, credential_row_gone: bool, shared: bool
    ) -> None:
        first = self._table("orders")
        self._migrate()
        old_source = _schema_for(first).source
        old_source.connection_metadata = {
            MIGRATION_MARKER_KEY: {
                "group_key": "s3/eu-west-1/exports",
                "credential_id": str(uuid.uuid4()) if credential_row_gone else str(self.credential.pk),
            }
        }
        old_source.save()
        second = self._table(
            "refunds",
            url="https://exports.s3.eu-west-1.amazonaws.com/refunds/*.csv",
            credential=self._credential("AKIAFIRST", secret),
        )

        [outcome] = self._migrate(table_ids=(str(second.id),))

        assert outcome.action == "linked"
        assert (_schema_for(second).source_id == old_source.pk) is shared

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
        assert schema.created_at == created_at
        assert schema.source.created_at == created_at
        assert SourceInputsStore.load(schema.source)["url_pattern"] == "https://s3.eu-west-1.amazonaws.com/exports/"
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

    @parameterized.expand(
        [
            ("named_region", "eu-west-1", "linked", False),
            ("unknown_region", None, "none", False),
            ("named_region_equal_valued_credential_rows", "eu-west-1", "linked", True),
        ]
    )
    def test_a_bucket_url_without_a_region_asks_s3_once_per_bucket(
        self, _name: str, region: str | None, expected_action: str, second_row: bool
    ) -> None:
        self._table("a", url="https://exports.s3.amazonaws.com/a/*.csv")
        self._table(
            "b",
            url="https://s3.amazonaws.com/exports/b/*.csv",
            credential=self._credential("AKIAFIRST") if second_row else None,
        )
        resolver = MagicMock(return_value=region)

        outcomes = self._migrate(resolve_region=resolver)

        assert [o.action for o in outcomes] == [expected_action] * 2
        resolver.assert_called_once()
        if region is not None:
            job_inputs = SourceInputsStore.load(ExternalDataSource.objects.get(team=self.team))
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


class TestMergeDuplicateSources(_MigrationTest):
    def _duplicates(self, count: int = 3) -> list[DataWarehouseTable]:
        tables = [
            self._table(
                f"table_{i}",
                url=f"https://exports.s3.eu-west-1.amazonaws.com/t{i}/*.csv",
                credential=self._credential(f"AKIATEMP{i}"),
            )
            for i in range(count)
        ]
        self._migrate()
        # Earlier runs keyed each source by its credential row, so equal keys in separate rows made a source each.
        for i, table in enumerate(tables):
            credential = table.credential
            assert credential is not None
            credential.access_key = "AKIAFIRST"
            credential.save()
            source = _schema_for(table).source
            inputs = SourceInputsStore.load(source)
            SourceInputsStore.save(
                source, {key: "AKIAFIRST" if value == f"AKIATEMP{i}" else value for key, value in inputs.items()}
            )
            ExternalDataSource.objects.filter(pk=source.pk).update(
                created_at=datetime(2024, 1, 1 + i, tzinfo=UTC),
                connection_metadata={
                    MIGRATION_MARKER_KEY: {"group_key": "s3/eu-west-1/exports", "credential_id": str(credential.pk)}
                },
            )
        assert len({_schema_for(table).source_id for table in tables}) == count
        return tables

    def test_duplicates_move_into_the_oldest_source_and_are_deleted(self) -> None:
        tables = self._duplicates()
        kept = _schema_for(tables[0]).source
        duplicates = [_schema_for(table).source for table in tables[1:]]
        moved_schema_ids = [str(_schema_for(table).id) for table in tables[1:]]

        outcomes = merge_duplicate_sources(team_id=self.team.pk, live_run=True)

        assert [(o.source_id, o.kept_source_id, o.action, o.moved_schemas) for o in outcomes] == [
            (str(source.pk), str(kept.pk), "merged", 1) for source in duplicates
        ]
        assert {_schema_for(table).source_id for table in tables} == {kept.pk}
        for source in duplicates:
            source.refresh_from_db()
            assert source.deleted is True
            assert not ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=source).exists()
        assert ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=kept).exists()
        assert sorted(call.args[0] for call in self.delete_schedule.call_args_list) == sorted(moved_schema_ids)
        assert {self._status(table).source_id for table in tables} == {str(kept.pk)}
        assert {self._status(table).state for table in tables} == {TableMigrationState.AWAITING_SYNC}
        assert merge_duplicate_sources(team_id=self.team.pk, live_run=True) == []
        added = self._table("late", url="https://exports.s3.eu-west-1.amazonaws.com/late/*.csv")
        self._migrate(table_ids=(str(added.id),))
        assert _schema_for(added).source_id == kept.pk

    def test_a_dry_run_reports_the_merge_and_changes_nothing(self) -> None:
        tables = self._duplicates(count=2)
        before = {table.pk: _schema_for(table).source_id for table in tables}
        out = StringIO()

        call_command("migrate_self_managed_tables", team_id=self.team.pk, merge_sources=True, stdout=out)

        duplicate_id = before[tables[1].pk]
        lines = out.getvalue().splitlines()
        assert lines[0] == (
            f"source={duplicate_id} team={self.team.pk} kept={before[tables[0].pk]} would_merge schemas=1"
        )
        assert "1 duplicate source(s), 1 schema(s): 1 would_merge" in out.getvalue()
        assert {table.pk: _schema_for(table).source_id for table in tables} == before
        assert ExternalDataSource.objects.get(pk=duplicate_id).deleted is False
        self.delete_schedule.assert_not_called()

    @parameterized.expand(
        [
            ("syncing_on", "syncing is on for 'table_1'"),
            ("job_ran", "a sync already ran for the source"),
            ("table_adopted", "the table 'table_1' is already adopted by a source"),
            ("name_taken_in_kept_source", "the kept source already has a table named 'table_1'"),
            ("source_has_rules", "the kept and the duplicate source have different access rules"),
            ("other_destinations", "the kept and the duplicate source send data to different destinations"),
            ("inputs_edited", "the kept and the duplicate source connect with different settings"),
        ]
    )
    def test_a_duplicate_that_is_not_safe_to_move_is_skipped(self, case: str, reason: str) -> None:
        tables = self._duplicates()
        kept = _schema_for(tables[0]).source
        unsafe = _schema_for(tables[1])
        safe_source_id = _schema_for(tables[2]).source_id
        if case == "syncing_on":
            ExternalDataSchema.objects.filter(pk=unsafe.pk).update(should_sync=True)
        elif case == "job_ran":
            self._job(tables[1], ExternalDataJobStatus.FAILED)
        elif case == "table_adopted":
            DataWarehouseTable.raw_objects.filter(pk=tables[1].pk).update(external_data_source=unsafe.source)
        elif case == "name_taken_in_kept_source":
            ExternalDataSchema.objects.create(name="table_1", team=self.team, source=kept)
        elif case == "source_has_rules":
            AccessControl.objects.create(
                team=self.team, resource="external_data_source", resource_id=str(unsafe.source_id), access_level="none"
            )
        elif case == "other_destinations":
            ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source_id=unsafe.source_id).delete()
        else:
            source = unsafe.source
            SourceInputsStore.save(source, {**SourceInputsStore.load(source), "file_format": "csv"})

        outcomes = {o.source_id: o for o in merge_duplicate_sources(team_id=self.team.pk, live_run=True)}

        skipped = outcomes[str(unsafe.source_id)]
        assert (skipped.action, skipped.reason, skipped.moved_schemas) == ("skipped", reason, 0)
        assert ExternalDataSchema.objects.get(pk=unsafe.pk).source_id == unsafe.source_id
        assert ExternalDataSource.objects.get(pk=unsafe.source_id).deleted is False
        assert outcomes[str(safe_source_id)].action == "merged"
        assert _schema_for(tables[2]).source_id == kept.pk

    def test_sources_with_another_key_or_bucket_stay_apart(self) -> None:
        self._duplicates(count=1)
        self._table("other_key", credential=self._credential("AKIAFIRST", "b3RoZXI="))
        self._table("other_bucket", url="https://archive.s3.eu-west-1.amazonaws.com/a.csv")
        self._migrate()

        assert merge_duplicate_sources(team_id=self.team.pk, live_run=True) == []
        assert ExternalDataSource.objects.filter(team=self.team, deleted=False).count() == 3


class TestBackdateMigrationSources(_MigrationTest):
    def _legacy_tables(self) -> list[DataWarehouseTable]:
        tables = [
            self._table("orders", created_at=datetime(2024, 1, 1, tzinfo=UTC)),
            self._table(
                "refunds",
                url="https://exports.s3.eu-west-1.amazonaws.com/refunds/*.csv",
                created_at=datetime(2024, 2, 1, tzinfo=UTC),
            ),
        ]
        self._migrate()
        source_id = _schema_for(tables[0]).source_id
        legacy_date = datetime(2030, 1, 1, tzinfo=UTC)
        ExternalDataSource.objects.filter(pk=source_id).update(created_at=legacy_date)
        ExternalDataSchema.objects.filter(source_id=source_id).update(created_at=legacy_date)
        return tables

    def test_dry_run_reports_the_date_without_changing_rows(self) -> None:
        tables = self._legacy_tables()
        source = _schema_for(tables[0]).source
        schemas = [_schema_for(table) for table in tables]
        source_updated_at = source.updated_at
        schema_updated_at = [schema.updated_at for schema in schemas]

        [outcome] = backdate_migration_sources(team_id=self.team.pk, live_run=False)

        assert (outcome.source_id, outcome.team_id, outcome.action) == (str(source.pk), self.team.pk, "would_backdate")
        assert (outcome.old_created_at, outcome.new_created_at) == (source.created_at, tables[0].created_at)
        source.refresh_from_db()
        assert source.created_at == datetime(2030, 1, 1, tzinfo=UTC)
        assert source.updated_at == source_updated_at
        for schema, updated_at in zip(schemas, schema_updated_at):
            schema.refresh_from_db()
            assert schema.created_at == datetime(2030, 1, 1, tzinfo=UTC)
            assert schema.updated_at == updated_at

    def test_live_run_backdates_source_and_each_schema_using_deleted_tables(self) -> None:
        tables = self._legacy_tables()
        DataWarehouseTable.raw_objects.filter(pk=tables[0].pk).update(deleted=True)
        source = _schema_for(tables[0]).source
        source_updated_at = source.updated_at
        schema_updated_at = {table.pk: _schema_for(table).updated_at for table in tables}

        [outcome] = backdate_migration_sources(team_id=self.team.pk, live_run=True)

        assert (outcome.action, outcome.old_created_at, outcome.new_created_at) == (
            "backdated",
            datetime(2030, 1, 1, tzinfo=UTC),
            tables[0].created_at,
        )
        source.refresh_from_db()
        assert source.created_at == tables[0].created_at
        assert source.updated_at == source_updated_at
        for table in tables:
            schema = _schema_for(table)
            assert schema.created_at == table.created_at
            assert schema.updated_at == schema_updated_at[table.pk]

    def test_live_run_backdates_a_deleted_source_and_its_deleted_schemas(self) -> None:
        tables = self._legacy_tables()
        source = _schema_for(tables[0]).source
        ExternalDataSchema.objects.filter(source_id=source.pk).update(deleted=True)
        ExternalDataSource.objects.filter(pk=source.pk).update(deleted=True)

        [outcome] = backdate_migration_sources(team_id=self.team.pk, live_run=True)

        assert (outcome.source_id, outcome.action) == (str(source.pk), "backdated")
        assert ExternalDataSource.objects.get(pk=source.pk).created_at == tables[0].created_at
        assert {schema.created_at for schema in ExternalDataSchema.objects.filter(source_id=source.pk)} == {
            table.created_at for table in tables
        }

    def test_source_at_its_oldest_table_date_is_unchanged(self) -> None:
        table = self._table(created_at=datetime(2024, 1, 1, tzinfo=UTC))
        self._migrate()
        source = _schema_for(table).source

        [outcome] = backdate_migration_sources(team_id=self.team.pk, live_run=True)

        assert (outcome.source_id, outcome.action, outcome.new_created_at) == (str(source.pk), "unchanged", None)
        assert ExternalDataSource.objects.get(pk=source.pk).created_at == table.created_at

    def test_non_migration_source_is_not_touched(self) -> None:
        table = self._table(created_at=datetime(2024, 1, 1, tzinfo=UTC))
        self._migrate()
        migration_schema = _schema_for(table)
        regular_source = ExternalDataSource.objects.create(team=self.team, source_type="Postgres", job_inputs={})
        regular_schema = ExternalDataSchema.objects.create(
            team=self.team,
            source=regular_source,
            name="regular",
            sync_type_config=migration_schema.sync_type_config,
        )
        later = datetime(2030, 1, 1, tzinfo=UTC)
        ExternalDataSource.objects.filter(pk=regular_source.pk).update(created_at=later)
        ExternalDataSchema.objects.filter(pk=regular_schema.pk).update(created_at=later)

        outcomes = backdate_migration_sources(team_id=self.team.pk, live_run=True)

        assert len(outcomes) == 1
        assert outcomes[0].source_id == str(migration_schema.source_id)
        regular_source.refresh_from_db()
        regular_schema.refresh_from_db()
        assert regular_source.created_at == later
        assert regular_schema.created_at == later

    @parameterized.expand([("dry_run", False, "would_backdate"), ("live_run", True, "backdated")])
    def test_command_reports_changed_sources_and_counts(self, _name: str, live_run: bool, action: str) -> None:
        tables = self._legacy_tables()
        source = _schema_for(tables[0]).source
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        ExternalDataSource.objects.create(
            team=other_team,
            source_type="Postgres",
            job_inputs={},
            connection_metadata={MIGRATION_MARKER_KEY: {}},
        )
        out = StringIO()

        call_command(
            "migrate_self_managed_tables",
            team_id=self.team.pk,
            backfill_created_at=True,
            live_run=live_run,
            stdout=out,
        )

        assert out.getvalue().splitlines()[0] == (
            f"source={source.pk} team={self.team.pk} {source.created_at.isoformat()} "
            f"-> {tables[0].created_at.isoformat()} {action}"
        )
        assert f"1 source(s): 1 {action}" in out.getvalue()
        source.refresh_from_db()
        assert source.created_at == (tables[0].created_at if live_run else datetime(2030, 1, 1, tzinfo=UTC))


class TestMigrateSelfManagedTablesCommand(BaseTest):
    @parameterized.expand(
        [
            ("zero_limit", {"limit": 0}, "--limit"),
            ("status_and_abandon", {"status": True, "abandon": "x"}, "only one"),
            ("status_and_merge", {"status": True, "merge_sources": True}, "only one"),
            ("abandon_and_merge", {"abandon": "x", "merge_sources": True}, "only one"),
            ("status_and_backfill", {"status": True, "backfill_created_at": True}, "only one"),
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

    def test_an_uploaded_table_sets_its_source_and_schema_dates(self) -> None:
        created_at = datetime(2024, 3, 1, tzinfo=UTC)
        table = self._uploaded("orders", "managed/team_{team}/orders.csv")
        DataWarehouseTable.raw_objects.filter(pk=table.pk).update(created_at=created_at)
        table.refresh_from_db()

        [outcome] = self._migrate()

        schema = _schema_for(table)
        assert outcome.action == "linked"
        assert schema.created_at == created_at
        assert schema.source.created_at == created_at

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
                "json_unknown_time_zone",
                DataWarehouseTableFormat.JSON,
                {"at": {"clickhouse": "DateTime('Nowhere/Land')", "hogql": "DateTimeDatabaseField"}},
                "time zone 'Nowhere/Land'",
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

    def test_an_uploaded_table_with_nested_columns_is_linked_and_reports_the_type(self) -> None:
        table = self._uploaded("orders", "managed/team_{team}/orders.parquet", DataWarehouseTableFormat.Parquet)
        DataWarehouseTable.raw_objects.filter(pk=table.pk).update(
            columns={"tags": {"clickhouse": "Array(Nullable(String))", "hogql": "StringArrayDatabaseField"}}
        )

        dry_run = StringIO()
        call_command("migrate_self_managed_tables", team_id=self.team.pk, stdout=dry_run)

        note = "note=(after the first sync these columns are stored as JSON text: tags (Array(Nullable(String))))"
        dry_run_line = dry_run.getvalue().splitlines()[0]
        assert "state=pending (not linked yet)" in dry_run_line
        assert note in dry_run_line
        assert "action=would_link" in dry_run_line

        [outcome] = self._migrate()

        assert (outcome.action, outcome.status.state) == ("linked", TableMigrationState.AWAITING_SYNC)
        assert _schema_for(table).should_sync is False

        linked_status = StringIO()
        call_command("migrate_self_managed_tables", team_id=self.team.pk, stdout=linked_status)
        linked_line = linked_status.getvalue().splitlines()[0]
        assert "state=awaiting_sync" in linked_line
        assert "action=none" in linked_line
        assert note in linked_line

    @parameterized.expand(
        [
            ("date", "Nullable(Date)", "date"),
            ("datetime", "DateTime64(3)", "datetime"),
            ("datetime_with_time_zone", "DateTime('Europe/London')", {"kind": "datetime", "timezone": "Europe/London"}),
        ]
    )
    def test_an_uploaded_json_table_with_a_date_column_keeps_the_date_type(
        self, _name: str, clickhouse_type: str, stored: Any
    ) -> None:
        table = self._uploaded("events", "managed/team_{team}/events.jsonl", DataWarehouseTableFormat.JSON)
        DataWarehouseTable.raw_objects.filter(pk=table.pk).update(
            columns={"day": {"clickhouse": clickhouse_type, "hogql": "DateDatabaseField"}}
        )

        [outcome] = self._migrate()

        assert outcome.status.state == TableMigrationState.AWAITING_SYNC
        schema_metadata = _schema_for(table).schema_metadata
        assert schema_metadata is not None
        assert schema_metadata["csv"]["column_types"] == {"day": stored}

    def test_uploaded_tables_sources_never_merge(self) -> None:
        self._uploaded("orders", "managed/team_{team}/orders.csv")
        self._uploaded("refunds", "managed/team_{team}/refunds.csv")
        self._migrate()

        assert merge_duplicate_sources(team_id=self.team.pk, live_run=True) == []
        assert ExternalDataSource.objects.filter(team=self.team, deleted=False).count() == 2

    def test_selection_takes_only_the_teams_own_uploaded_tables(self) -> None:
        self._uploaded("uploaded", "file_uploads/team_{team}/{upload}/orders.csv")
        self._uploaded("legacy", "managed/team_{team}/orders.csv")
        self._uploaded("materialized_view", "dlt/team_{team}_model_abc/modeling/orders")
        self._uploaded("another_teams_file", "managed/team_999999/orders.csv")
        self._uploaded("nested_key", "managed/team_{team}/sub/orders.csv")
        # A table made from an upload links to its own file upload source and waits for its first sync.
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


_LEVELS = ("none", "viewer", "editor", "manager")
_ROLE_NAMES = ("A", "B")
# Each member stands for one way a member can relate to the rules.
_MEMBERS: dict[str, tuple[tuple[str, ...], OrganizationMembership.Level]] = {
    "plain": ((), OrganizationMembership.Level.MEMBER),
    "named": ((), OrganizationMembership.Level.MEMBER),
    "in_role": (("A",), OrganizationMembership.Level.MEMBER),
    "named_in_roles": (("A", "B"), OrganizationMembership.Level.MEMBER),
    "in_both_roles": (("A", "B"), OrganizationMembership.Level.MEMBER),
    "admin": ((), OrganizationMembership.Level.ADMIN),
    "project_admin": ((), OrganizationMembership.Level.MEMBER),
    "creator": ((), OrganizationMembership.Level.MEMBER),
}
# Where a rule can be: "<scope>" is the scope's default rule, "<scope>:<member or role>" names a subject.
_SCOPES = {
    "table": ("warehouse_table", True),
    "warehouse": ("warehouse_objects", False),
    "sources": ("external_data_source", False),
    # Resolution reads the rules for all warehouse tables from warehouse_objects, so this rule never applies.
    "all_tables": ("warehouse_table", False),
}


class _AccessRulesTest(_MigrationTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": feature, "name": feature}
            for feature in (AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS)
        ]
        self.organization.save()
        self.roles = {
            name: create_role(organization_id=self.organization.id, name=f"Role {name}") for name in _ROLE_NAMES
        }
        self.users: dict[str, User] = {}
        self.memberships: dict[str, OrganizationMembership] = {}
        for name, (roles, level) in _MEMBERS.items():
            user = User.objects.create_and_join(self.organization, f"{name}@example.com", None, level=level)
            self.users[name] = user
            self.memberships[name] = OrganizationMembership.objects.get(user=user, organization=self.organization)
            for role in roles:
                add_role_member(role_id=self.roles[role], user_id=user.id)
        create_access_control(
            team_id=self.team.pk,
            resource="project",
            resource_id=str(self.team.pk),
            access_level="admin",
            organization_member_id=self.memberships["project_admin"].id,
        )

    def _rule(self, slot: str, level: str, table: DataWarehouseTable | None = None) -> None:
        scope, _, subject = slot.partition(":")
        resource, on_table = _SCOPES[scope]
        create_access_control(
            team_id=self.team.pk,
            resource=resource,
            resource_id=str(table.id) if on_table and table is not None else None,
            access_level=level,
            organization_member_id=self.memberships[subject].id if subject in self.memberships else None,
            role_id=self.roles[subject] if subject in self.roles else None,
        )

    def _apply(self, rules: dict[str, str], table: DataWarehouseTable) -> None:
        for slot, level in rules.items():
            self._rule(slot, level, table)

    def _access(self, obj: Any) -> dict[str, str | None]:
        """Each subject's access to the object, from the access checks that serve requests."""
        result: dict[str, str | None] = {
            name: UserAccessControl(user, self.team).get_user_access_level(obj) for name, user in self.users.items()
        }
        asker = UserAccessControl(self.users["admin"], self.team)
        for name, role_id in self.roles.items():
            result[f"role {name}"] = SubjectAccessControl.for_role(
                asker, self.team, str(role_id)
            ).get_user_access_level(obj)
        result["everyone"] = SubjectAccessControl.for_default(asker, self.team).get_user_access_level(obj)
        return result

    def _in_both_orders(self, obj: Any) -> dict[bool, dict[str, str | None]]:
        by_order = {}
        for most_specific in (False, True):
            self.organization.uses_most_specific_access_resolution = most_specific
            self.organization.save()
            by_order[most_specific] = self._access(obj)
        return by_order

    def _source_rules(self, source: ExternalDataSource) -> set[tuple[str, str]]:
        names = {str(m.id): name for name, m in self.memberships.items()} | {str(r): n for n, r in self.roles.items()}
        return {
            (names.get(str(rule.organization_member_id or rule.role_id or ""), ""), rule.access_level)
            for rule in AccessControl.objects.filter(
                team=self.team, resource="external_data_source", resource_id=str(source.pk)
            )
        }

    def _assert_move_keeps_access(self, table: DataWarehouseTable) -> ExternalDataSource:
        """Adopt the linked table, and check every subject's access to it and to its source under both orders."""
        before = self._in_both_orders(table)
        source = _schema_for(table).source
        self._adopt(table)
        table.refresh_from_db()
        assert table.external_data_source_id == source.pk
        after = self._in_both_orders(table)
        on_source = self._in_both_orders(source)
        assert after == before
        for most_specific, levels in on_source.items():
            for subject, level in levels.items():
                table_level = after[most_specific][subject]
                assert level is not None and table_level is not None
                assert _LEVELS.index(level) <= _LEVELS.index(table_level), (most_specific, subject, level, table_level)
        return source


class TestAccessRulesMoveWithTheTable(_AccessRulesTest):
    @parameterized.expand(
        [
            ("no_rules", {}, set()),
            ("table_private", {"table": "none"}, {("", "none")}),
            ("table_read_only", {"table": "viewer"}, {("", "viewer")}),
            ("table_hidden_from_a_member", {"table:named": "none"}, {("named", "none")}),
            (
                "table_private_but_shared_with_a_member",
                {"table": "none", "table:named": "editor"},
                {("named", "editor"), ("", "none")},
            ),
            ("table_rule_for_a_role", {"table:A": "viewer"}, {("A", "viewer")}),
            (
                "member_rule_and_role_rule_for_one_member",
                {"table:named_in_roles": "viewer", "table:A": "editor", "table:B": "none"},
                {("named_in_roles", "viewer"), ("A", "editor"), ("B", "none")},
            ),
            ("warehouse_read_only", {"warehouse": "viewer"}, {("", "viewer")}),
            ("warehouse_hidden", {"warehouse": "none"}, {("", "none")}),
            ("warehouse_managers", {"warehouse": "manager"}, set()),
            # The table gives more than the default for sources, so the source must grant it.
            ("sources_read_only", {"sources": "viewer"}, {("", "editor")}),
            # The table gives less than the default for sources, so the source must be restricted.
            ("private_table_and_sources_open", {"table": "none", "sources": "editor"}, {("", "none")}),
            ("private_table_and_warehouse_read_only", {"table": "none", "warehouse": "viewer"}, {("", "none")}),
            ("rule_for_all_tables_never_applies", {"all_tables": "none"}, set()),
            ("rule_for_the_project_admin", {"table:project_admin": "none"}, {("project_admin", "none")}),
            ("rule_for_the_creator", {"table:creator": "none"}, {("creator", "none")}),
        ]
    )
    def test_a_migrated_table_keeps_every_subjects_access(
        self, _name: str, rules: dict[str, str], source_rules: set[tuple[str, str]]
    ) -> None:
        table = self._table(created_by=self.users["creator"])
        self._apply(rules, table)
        before = self._in_both_orders(table)

        [outcome] = self._migrate()

        assert outcome.action == "linked", outcome.error or outcome.status.reason
        assert self._source_rules(_schema_for(table).source) == source_rules
        # Until the first sync the table has no source, so the source's rules don't reach it.
        assert self._in_both_orders(table) == before
        self._assert_move_keeps_access(table)

    @parameterized.expand(
        [
            # A grant on a source can't widen "none" for all sources under most-specific resolution.
            ("sources_hidden", {"sources": "none"}, "access rules for sources"),
            ("sources_hidden_from_a_member", {"sources:named": "none"}, "access rules for sources"),
            ("table_read_only_and_sources_hidden", {"table": "viewer", "sources": "none"}, "access rules for sources"),
            # Everyone could manage the source, and through its rules change the table's access.
            ("sources_managed_by_everyone", {"sources": "manager"}, "access rules for sources"),
            # Members of one role see more of the warehouse than the others, and one default can't say that.
            ("warehouse_open_to_a_role", {"warehouse": "viewer", "warehouse:A": "editor"}, "access rules for sources"),
            ("warehouse_hidden_from_a_member", {"warehouse:named": "none"}, "access rules for sources"),
            (
                "table_rule_and_sources_hidden_from_a_role",
                {"table:named": "viewer", "sources:A": "none"},
                "access rules for sources",
            ),
        ]
    )
    def test_a_table_whose_access_no_source_rules_can_keep_stays_self_managed(
        self, _name: str, rules: dict[str, str], reason: str
    ) -> None:
        table = self._table()
        self._apply(rules, table)

        [outcome] = self._migrate()

        assert outcome.status.state == TableMigrationState.SKIPPED
        assert reason in (outcome.status.reason or "")
        assert _schemas_for(table) == []
        assert not ExternalDataSource.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            (f"table_{table}_warehouse_{warehouse}_sources_{sources}", table, warehouse, sources)
            for table in (None, *_LEVELS[:3])
            for warehouse in (None, *_LEVELS[:3])
            for sources in (None, *_LEVELS[:3])
        ]
    )
    def test_every_move_of_a_table_with_explicit_rules_keeps_access(
        self, _name: str, table_default: str | None, warehouse: str | None, sources: str | None
    ) -> None:
        table = self._table(created_by=self.users["creator"])
        rules = {"table:named": "viewer", "table:B": "none"}
        for slot, level in (("table", table_default), ("warehouse", warehouse), ("sources", sources)):
            if level is not None:
                rules[slot] = level
        self._apply(rules, table)

        [outcome] = self._migrate()

        if outcome.action != "linked":
            assert outcome.status.state == TableMigrationState.SKIPPED
            assert outcome.status.reason in (
                "the table has its own access rules, which the source PostHog would create can't carry",
                "the project has access rules for sources or for the warehouse, which the move would change",
            )
            return
        self._assert_move_keeps_access(table)

    def test_tables_of_one_bucket_share_a_source_only_when_they_need_the_same_rules(self) -> None:
        open_table = self._table("open", url="https://exports.s3.eu-west-1.amazonaws.com/open/*.csv")
        private = self._table("private", url="https://exports.s3.eu-west-1.amazonaws.com/private/*.csv")
        also_private = self._table("also_private", url="https://exports.s3.eu-west-1.amazonaws.com/also/*.csv")
        read_only = self._table("read_only", url="https://exports.s3.eu-west-1.amazonaws.com/read/*.csv")
        self._rule("table", "none", private)
        self._rule("table", "none", also_private)
        self._rule("table", "viewer", read_only)

        self._migrate()

        sources = {table.name: _schema_for(table).source for table in (open_table, private, also_private, read_only)}
        assert sources["private"].pk == sources["also_private"].pk
        assert len({source.pk for source in sources.values()}) == 3
        assert self._source_rules(sources["open"]) == set()
        assert self._source_rules(sources["private"]) == {("", "none")}
        assert self._source_rules(sources["read_only"]) == {("", "viewer")}
        assert "access_signature" not in (sources["open"].connection_metadata or {})[MIGRATION_MARKER_KEY]
        for table in (private, also_private, read_only):
            self._assert_move_keeps_access(table)

    def test_rules_that_never_apply_are_not_copied(self) -> None:
        other_organization = Organization.objects.create(name="Elsewhere")
        foreign_role = create_role(organization_id=other_organization.id, name="Foreign")
        table = self._table()
        create_access_control(
            team_id=self.team.pk,
            resource="warehouse_table",
            resource_id=str(table.id),
            access_level="none",
            role_id=foreign_role,
        )
        before = self._in_both_orders(table)

        [outcome] = self._migrate()

        assert outcome.action == "linked"
        assert self._source_rules(_schema_for(table).source) == set()
        assert self._in_both_orders(table) == before
        self._assert_move_keeps_access(table)

    def test_a_rule_for_an_inactive_member_is_copied(self) -> None:
        User.objects.filter(pk=self.users["named"].pk).update(is_active=False)
        table = self._table()
        self._rule("table:named", "manager", table)

        [outcome] = self._migrate()

        assert outcome.action == "linked"
        assert self._source_rules(_schema_for(table).source) == {("named", "manager")}

    def test_rules_of_an_organization_without_access_control_are_copied_for_when_it_comes_back(self) -> None:
        table = self._table()
        self._apply({"table": "none", "table:named": "viewer"}, table)
        with_access_control = self._in_both_orders(table)
        self.organization.available_product_features = []
        self.organization.save()

        [outcome] = self._migrate()

        assert outcome.action == "linked"
        assert self._source_rules(_schema_for(table).source) == {("named", "viewer"), ("", "none")}
        self._assert_move_keeps_access(table)
        self.organization.available_product_features = [
            {"key": feature, "name": feature}
            for feature in (AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS)
        ]
        self.organization.save()
        assert self._in_both_orders(table) == with_access_control

    @parameterized.expand(
        [
            ("unknown_level", {"table": "superuser"}, "the level 'superuser'"),
        ]
    )
    def test_rules_the_planner_cant_read_keep_the_table_self_managed(
        self, _name: str, rules: dict[str, str], reason: str
    ) -> None:
        table = self._table()
        self._apply(rules, table)

        [outcome] = self._migrate()

        assert outcome.status.state == TableMigrationState.SKIPPED
        assert reason in (outcome.status.reason or "")

    def test_rules_that_name_too_many_roles_keep_the_table_self_managed(self) -> None:
        table = self._table()
        for i in range(11):
            role = create_role(organization_id=self.organization.id, name=f"Extra {i}")
            create_access_control(
                team_id=self.team.pk,
                resource="warehouse_table",
                resource_id=str(table.id),
                access_level=_LEVELS[i % 4],
                role_id=role,
            )
            create_access_control(
                team_id=self.team.pk, resource="warehouse_objects", access_level=_LEVELS[i // 4], role_id=role
            )

        [outcome] = self._migrate()

        assert outcome.status.state == TableMigrationState.SKIPPED
        assert outcome.status.reason == "the access rules name too many roles to check"

    def test_status_and_dry_run_report_the_rules_the_source_gets_and_write_nothing(self) -> None:
        table = self._table()
        self._apply({"table": "none", "table:named": "editor"}, table)
        member_id = self.memberships["named"].id
        note = f"note=(the source gets these access rules: member {member_id}=editor, everyone=none)"

        for options in ({"status": True}, {}):
            out = StringIO()
            call_command("migrate_self_managed_tables", team_id=self.team.pk, stdout=out, **options)
            assert note in out.getvalue()

        assert not ExternalDataSource.objects.filter(team=self.team).exists()
        assert not AccessControl.objects.filter(resource="external_data_source").exists()

    def test_an_uploaded_table_gets_the_same_rules_on_its_own_source(self) -> None:
        with override_settings(DATAWAREHOUSE_BUCKET=UPLOAD_BUCKET, DATAWAREHOUSE_BUCKET_DOMAIN=UPLOAD_DOMAIN):
            table = self._table(
                "uploaded",
                url=f"https://{UPLOAD_DOMAIN}/file_uploads/team_{self.team.pk}/{UPLOAD_ID}/orders.csv",
                created_by=self.users["creator"],
            )
            DataWarehouseTable.raw_objects.filter(pk=table.pk).update(
                credential=None, options={"csv_allow_double_quotes": False}
            )
            table.refresh_from_db()
            self._apply({"table": "none", "table:A": "viewer"}, table)

            [outcome] = self._migrate()

        assert outcome.action == "linked", outcome.error or outcome.status.reason
        source = _schema_for(table).source
        assert source.source_type == "FileUpload"
        assert self._source_rules(source) == {("A", "viewer"), ("", "none")}
        assert (source.connection_metadata or {})[MIGRATION_MARKER_KEY]["access_signature"]
        self._assert_move_keeps_access(table)


class TestAccessRulesAfterLinking(_AccessRulesTest):
    def _linked(self, rules: dict[str, str], name: str = "orders") -> DataWarehouseTable:
        table = self._table(name, url=f"https://exports.s3.eu-west-1.amazonaws.com/{name}/*.csv")
        self._apply(rules, table)
        [outcome] = self._migrate(table_ids=(str(table.id),))
        assert outcome.action == "linked"
        return table

    @parameterized.expand(
        [
            ("no_change", None, None),
            ("table_rule_added", "table:named", "the access rules of the table or of its source changed"),
            ("table_rule_widened", "table", "the access rules of the table or of its source changed"),
            ("source_rule_edited", "source", "the access rules of the table or of its source changed"),
            ("sources_hidden", "sources", "now the project has access rules for sources"),
        ]
    )
    def test_the_first_sync_refuses_to_adopt_a_table_whose_rules_changed(
        self, _name: str, change: str | None, refusal: str | None
    ) -> None:
        table = self._linked({"table": "viewer"})
        source = _schema_for(table).source
        if change == "table:named":
            self._rule("table:named", "viewer", table)
        elif change == "table":
            AccessControl.objects.filter(resource="warehouse_table", resource_id=str(table.id)).update(
                access_level="editor"
            )
        elif change == "source":
            AccessControl.objects.filter(resource="external_data_source", resource_id=str(source.pk)).update(
                access_level="none"
            )
        elif change == "sources":
            self._rule("sources", "none")

        status = self._status(table)
        if refusal is None:
            assert_adoption_keeps_access(table, source)
            assert status.reason == "syncing is off"
            return
        with self.assertRaisesRegex(AdoptionAccessError, refusal):
            assert_adoption_keeps_access(table, source)
        assert status.state == TableMigrationState.AWAITING_SYNC
        assert refusal in (status.reason or "")
        assert "the first sync will fail and leave the table as it is" in (status.reason or "")

    @parameterized.expand([("unchanged", False, False), ("rule_added", True, False), ("already_adopted", True, True)])
    def test_the_import_stops_before_extraction_only_when_the_rules_no_longer_fit(
        self, _name: str, rule_added: bool, adopted: bool
    ) -> None:
        table = self._linked({"table": "viewer"})
        if rule_added:
            self._rule("table:named", "viewer", table)
        if adopted:
            self._adopt(table)

        error = self_managed_adoption_error(_schema_for(table) if not adopted else self._unlinked_schema(table))

        if not rule_added or adopted:
            assert error is None
            return
        assert error is not None
        assert error.startswith(f"{ADOPTION_ACCESS_ERROR} 'orders', because the access rules of the table")
        assert "an organization admin must make the access rules of this source the same" in error

    def _unlinked_schema(self, table: DataWarehouseTable) -> ExternalDataSchema:
        schema = _schema_for(table)
        ExternalDataSchema.objects.filter(pk=schema.pk).update(table=None)
        schema.refresh_from_db()
        return schema

    def test_a_source_made_before_access_signatures_takes_only_tables_without_rules(self) -> None:
        old = self._linked({})
        source = _schema_for(old).source
        assert MIGRATION_MARKER_KEY in (source.connection_metadata or {})
        assert "access_signature" not in (source.connection_metadata or {})[MIGRATION_MARKER_KEY]
        plain = self._linked({}, name="plain")
        private = self._linked({"table": "none"}, name="private")

        assert _schema_for(plain).source_id == source.pk
        assert _schema_for(private).source_id != source.pk
        assert self._source_rules(source) == set()

    def test_a_table_does_not_join_a_source_whose_rules_someone_changed(self) -> None:
        first = self._linked({"table": "none"}, name="first")
        source = _schema_for(first).source
        AccessControl.objects.filter(resource="external_data_source", resource_id=str(source.pk)).update(
            access_level="viewer"
        )
        second = self._table("second", url="https://exports.s3.eu-west-1.amazonaws.com/second/*.csv")
        self._rule("table", "none", second)

        [outcome] = self._migrate(table_ids=(str(second.id),))

        assert outcome.action == "link_failed"
        assert "the access rules on the source for this bucket changed" in (outcome.error or "")
        assert ExternalDataSource.objects.filter(team=self.team, deleted=False).count() == 1

    @parameterized.expand([("last_table", False), ("other_tables_stay", True)])
    def test_abandon_removes_the_rules_only_with_the_source(self, _name: str, keep_another: bool) -> None:
        table = self._linked({"table": "none"})
        source = _schema_for(table).source
        if keep_another:
            other = self._linked({"table": "none"}, name="other")
            assert _schema_for(other).source_id == source.pk

        assert self._abandon(table).action == "abandoned"

        source.refresh_from_db()
        assert source.deleted is not keep_another
        assert self._source_rules(source) == (({("", "none")}) if keep_another else set())

    def test_abandon_of_a_table_never_linked_leaves_no_rules(self) -> None:
        table = self._table()
        self._rule("table", "none", table)

        assert self._abandon(table).action == "abandoned"

        assert not AccessControl.objects.filter(resource="external_data_source").exists()

    def test_a_rule_written_while_the_run_plans_fails_the_link(self) -> None:
        table = self._table()
        planned_reads: list[TeamAccessRules] = []

        def rules_read_then_changed(team_id: int) -> TeamAccessRules:
            rules = TeamAccessRules(team_id)
            if not planned_reads:
                self._rule("table", "none", table)
            planned_reads.append(rules)
            return rules

        with patch(f"{MODULE}.TeamAccessRules", side_effect=rules_read_then_changed):
            [outcome] = self._migrate()

        assert (outcome.action, outcome.error) == ("link_failed", "the access rules changed during the run")
        assert not ExternalDataSource.objects.filter(team=self.team).exists()


class TestMergeKeepsAccessRules(_AccessRulesTest):
    def _duplicate_pair(self, rules: dict[str, str]) -> tuple[DataWarehouseTable, DataWarehouseTable]:
        """Two sources of one group with the same rules, as earlier runs could leave them."""
        tables = []
        for i in range(2):
            table = self._table(
                f"table_{i}",
                url=f"https://exports.s3.eu-west-1.amazonaws.com/t{i}/*.csv",
                credential=self._credential(f"AKIATEMP{i}"),
            )
            self._apply(rules, table)
            tables.append(table)
        self._migrate()
        for i, table in enumerate(tables):
            credential = table.credential
            assert credential is not None
            credential.access_key = "AKIAFIRST"
            credential.save()
            source = _schema_for(table).source
            inputs = SourceInputsStore.load(source)
            SourceInputsStore.save(
                source, {key: "AKIAFIRST" if value == f"AKIATEMP{i}" else value for key, value in inputs.items()}
            )
            signature = (source.connection_metadata or {})[MIGRATION_MARKER_KEY].get("access_signature")
            ExternalDataSource.objects.filter(pk=source.pk).update(
                created_at=datetime(2024, 1, 1 + i, tzinfo=UTC),
                connection_metadata={
                    MIGRATION_MARKER_KEY: {
                        "group_key": "s3/eu-west-1/exports",
                        "credential_id": str(credential.pk),
                        **({"access_signature": signature} if signature else {}),
                    }
                },
            )
        assert _schema_for(tables[0]).source_id != _schema_for(tables[1]).source_id
        return tables[0], tables[1]

    def test_sources_with_the_same_rules_merge_and_the_duplicates_rules_go(self) -> None:
        first, second = self._duplicate_pair({"table": "none"})
        kept, duplicate = _schema_for(first).source, _schema_for(second).source

        [outcome] = merge_duplicate_sources(team_id=self.team.pk, live_run=True)

        assert (outcome.action, outcome.source_id) == ("merged", str(duplicate.pk))
        assert _schema_for(second).source_id == kept.pk
        assert self._source_rules(kept) == {("", "none")}
        assert self._source_rules(duplicate) == set()
        self._assert_move_keeps_access(second)

    @parameterized.expand([("rules_differ", "the kept and the duplicate source have different access rules")])
    def test_sources_whose_rules_differ_never_merge(self, _name: str, reason: str) -> None:
        first, second = self._duplicate_pair({"table": "none"})
        duplicate = _schema_for(second).source
        AccessControl.objects.filter(resource="external_data_source", resource_id=str(duplicate.pk)).update(
            access_level="viewer"
        )

        [outcome] = merge_duplicate_sources(team_id=self.team.pk, live_run=True)

        assert (outcome.action, outcome.reason) == ("skipped", reason)
        assert _schema_for(second).source_id == duplicate.pk

    def test_sources_with_other_access_signatures_are_never_grouped(self) -> None:
        open_table = self._table("open", url="https://exports.s3.eu-west-1.amazonaws.com/open/*.csv")
        private = self._table("private", url="https://exports.s3.eu-west-1.amazonaws.com/private/*.csv")
        self._rule("table", "none", private)
        self._migrate()
        assert _schema_for(open_table).source_id != _schema_for(private).source_id

        assert merge_duplicate_sources(team_id=self.team.pk, live_run=True) == []
