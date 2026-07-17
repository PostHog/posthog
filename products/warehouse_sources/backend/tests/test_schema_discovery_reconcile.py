import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    auto_enable_new_schemas,
    schema_name_matches_auto_sync_patterns,
    sync_old_schemas_with_new_schemas,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


# Managed/scheduled discovery calls sync_old_schemas_with_new_schemas with no rename step, so a
# qualified/bare name mismatch against the stored row used to flip the live row to should_sync=False.
class TestSchemaDiscoveryReconcile(BaseTest):
    def _make_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )

    def _make_synced_schema(self, source: ExternalDataSource, name: str) -> ExternalDataSchema:
        table = DataWarehouseTable.objects.create(
            name=f"postgres_{name}".replace(".", "_"),
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="https://bucket/team_1/*",
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"}},
        )
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name=name,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            table=table,
        )

    @parameterized.expand(
        [
            # (stored name on the live synced row, the single name discovery currently emits)
            ("stored_qualified_discovery_bare", "public.campaign_runs", "campaign_runs"),
            ("stored_bare_discovery_qualified", "campaign_runs", "public.campaign_runs"),
        ]
    )
    def test_discovery_does_not_disable_live_synced_schema_on_qualification_mismatch(
        self, _name: str, stored_name: str, discovered_name: str
    ) -> None:
        source = self._make_source()
        synced_schema = self._make_synced_schema(source, stored_name)

        # Discovery returns the same physical table under the other qualification.
        sync_old_schemas_with_new_schemas(
            {discovered_name: None},
            source_id=str(source.pk),
            team_id=self.team.pk,
        )

        synced_schema.refresh_from_db()
        assert synced_schema.should_sync is True, (
            f"live synced schema {stored_name!r} was disabled when discovery emitted {discovered_name!r} "
            "— qualification mismatch must not be treated as a removed table"
        )
        assert synced_schema.table_id is not None

    def test_multi_schema_same_named_tables_stay_distinct(self) -> None:
        # Multi-schema mode (no single schema configured) emits everything qualified. A new
        # same-named table in another schema must be created, not collapsed onto the existing one.
        source = self._make_source()
        existing = self._make_synced_schema(source, "public.users")

        created, _deleted = sync_old_schemas_with_new_schemas(
            {"public.users": None, "analytics.users": None},
            source_id=str(source.pk),
            team_id=self.team.pk,
        )

        existing.refresh_from_db()
        assert existing.should_sync is True
        assert "analytics.users" in created
        assert ExternalDataSchema.objects.filter(source_id=source.pk, name="analytics.users").exists()

    def test_strict_match_creates_qualified_row_alongside_legacy_bare_row(self) -> None:
        # GitHub keeps its legacy repo's rows bare forever, so a second repo's qualified rows
        # coexist with them. Without strict matching, `acme/other.issues` tail-matches the bare
        # `issues` row and repo #2's rows are silently never created.
        source = self._make_source()
        legacy = self._make_synced_schema(source, "issues")

        created, _deleted = sync_old_schemas_with_new_schemas(
            {"issues": None, "acme/other.issues": "acme/other · issues"},
            source_id=str(source.pk),
            team_id=self.team.pk,
            strict_name_match=True,
            schema_metadata_by_name={
                "acme/other.issues": {"source_repository": "acme/other", "source_endpoint": "issues"}
            },
        )

        legacy.refresh_from_db()
        assert legacy.should_sync is True
        assert created == ["acme/other.issues"]
        new_row = ExternalDataSchema.objects.get(source_id=source.pk, name="acme/other.issues")
        assert new_row.sync_type_config.get("schema_metadata") == {
            "source_repository": "acme/other",
            "source_endpoint": "issues",
        }

    def test_strict_match_retires_removed_repo_rows(self) -> None:
        # Removing a repo drops its names from discovery: synced rows keep their table but stop
        # syncing; never-synced rows soft-delete. The legacy bare row must survive untouched.
        source = self._make_source()
        legacy = self._make_synced_schema(source, "issues")
        synced_removed = self._make_synced_schema(source, "acme/other.issues")
        unsynced_removed = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="acme/other.commits", should_sync=False
        )

        sync_old_schemas_with_new_schemas(
            {"issues": None},
            source_id=str(source.pk),
            team_id=self.team.pk,
            strict_name_match=True,
        )

        legacy.refresh_from_db()
        synced_removed.refresh_from_db()
        unsynced_removed.refresh_from_db()
        assert legacy.should_sync is True
        assert synced_removed.should_sync is False
        assert synced_removed.deleted is False
        assert unsynced_removed.deleted is True


class TestSchemaNameMatchesAutoSyncPatterns(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_patterns", "raw_events", None, True),
            ("empty_list", "raw_events", [], True),
            ("blank_patterns_only", "raw_events", ["  ", ""], True),
            ("exact_match", "raw_events", ["raw_events"], True),
            ("prefix_glob", "raw_events", ["raw_*"], True),
            ("prefix_glob_matches_bare_tail_of_qualified_name", "public.raw_events", ["raw_*"], True),
            ("qualified_pattern_matches_full_name", "analytics.users", ["analytics.*"], True),
            ("case_insensitive", "RAW_Events", ["raw_*"], True),
            ("pattern_whitespace_is_stripped", "raw_events", [" raw_* "], True),
            ("question_mark_single_char", "raw_1", ["raw_?"], True),
            ("question_mark_rejects_longer_name", "raw_12", ["raw_?"], False),
            ("any_pattern_may_match", "billing_invoices", ["raw_*", "billing_*"], True),
            ("no_match", "public.users", ["raw_*"], False),
        ]
    )
    def test_matching(self, _name: str, schema_name: str, patterns: list[str] | None, expected: bool) -> None:
        assert schema_name_matches_auto_sync_patterns(schema_name, patterns) is expected


_SCHEDULE_FN = "products.data_warehouse.backend.facade.api.sync_external_data_job_workflow"


class TestAutoEnableNewSchemas(BaseTest):
    def _make_source(self, **kwargs) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
            **{"auto_sync_new_schemas": True, **kwargs},
        )

    def _make_discovered_row(self, source: ExternalDataSource, name: str, **kwargs) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name=name, should_sync=False, **kwargs
        )

    def _source_schema(self, name: str, **kwargs) -> SourceSchema:
        updated_at: IncrementalField = {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
        defaults: dict = {
            "supports_incremental": True,
            "supports_append": False,
            "incremental_fields": [updated_at],
            "detected_primary_keys": ["id"],
        }
        return SourceSchema(name=name, **{**defaults, **kwargs})

    def test_enables_matching_schema_with_smart_defaults_and_schedule(self) -> None:
        source = self._make_source(auto_sync_schema_patterns=["raw_*"])
        matching = self._make_discovered_row(
            source, "raw_events", sync_type_config={"schema_metadata": {"source_table_name": "raw_events"}}
        )
        non_matching = self._make_discovered_row(source, "audit_log")
        source_schemas = {name: self._source_schema(name) for name in ["raw_events", "audit_log"]}

        with patch(_SCHEDULE_FN) as mock_schedule:
            enabled = auto_enable_new_schemas(source, ["raw_events", "audit_log"], source_schemas)

        assert enabled == ["raw_events"]
        matching.refresh_from_db()
        assert matching.should_sync is True
        assert matching.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
        assert matching.sync_type_config["incremental_field"] == "updated_at"
        assert matching.sync_type_config["incremental_field_type"] == "datetime"
        assert matching.sync_type_config["primary_key_columns"] == ["id"]
        # Pre-seeded discovery metadata must survive the config merge
        assert matching.sync_type_config["schema_metadata"] == {"source_table_name": "raw_events"}
        non_matching.refresh_from_db()
        assert non_matching.should_sync is False
        assert non_matching.sync_type is None
        mock_schedule.assert_called_once()
        assert mock_schedule.call_args.args[0].id == matching.id
        assert mock_schedule.call_args.kwargs.get("create") is True

    def test_empty_patterns_enable_every_new_schema(self) -> None:
        source = self._make_source(auto_sync_schema_patterns=None)
        self._make_discovered_row(source, "raw_events")
        self._make_discovered_row(source, "audit_log")
        source_schemas = {name: self._source_schema(name) for name in ["raw_events", "audit_log"]}

        with patch(_SCHEDULE_FN):
            enabled = auto_enable_new_schemas(source, ["raw_events", "audit_log"], source_schemas)

        assert sorted(enabled) == ["audit_log", "raw_events"]
        assert ExternalDataSchema.objects.filter(source_id=source.pk, should_sync=True, deleted=False).count() == 2

    @parameterized.expand(
        [
            ("auto_sync_disabled", {"auto_sync_new_schemas": False}),
            ("direct_query_source", {"access_method": ExternalDataSource.AccessMethod.DIRECT}),
        ]
    )
    def test_no_op_when_opted_out_or_direct_query(self, _name: str, source_kwargs: dict) -> None:
        source = self._make_source(**source_kwargs)
        row = self._make_discovered_row(source, "raw_events")

        with patch(_SCHEDULE_FN) as mock_schedule:
            enabled = auto_enable_new_schemas(source, ["raw_events"], {"raw_events": self._source_schema("raw_events")})

        assert enabled == []
        row.refresh_from_db()
        assert row.should_sync is False
        mock_schedule.assert_not_called()

    def test_skips_rows_that_already_have_sync_config(self) -> None:
        # A revived soft-deleted row keeps its previous user config; auto-sync must not overwrite it.
        source = self._make_source()
        row = self._make_discovered_row(source, "raw_events", sync_type=ExternalDataSchema.SyncType.FULL_REFRESH)

        with patch(_SCHEDULE_FN) as mock_schedule:
            enabled = auto_enable_new_schemas(source, ["raw_events"], {"raw_events": self._source_schema("raw_events")})

        assert enabled == []
        row.refresh_from_db()
        assert row.should_sync is False
        assert row.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH
        mock_schedule.assert_not_called()

    @parameterized.expand(
        [
            ("webhook_only", {"webhook_only": True}),
            ("default_off", {"should_sync_default": False}),
        ]
    )
    def test_skips_tables_the_source_marks_as_opt_in(self, _name: str, schema_kwargs: dict) -> None:
        source = self._make_source()
        row = self._make_discovered_row(source, "raw_events")

        with patch(_SCHEDULE_FN) as mock_schedule:
            enabled = auto_enable_new_schemas(
                source, ["raw_events"], {"raw_events": self._source_schema("raw_events", **schema_kwargs)}
            )

        assert enabled == []
        row.refresh_from_db()
        assert row.should_sync is False
        mock_schedule.assert_not_called()

    def test_schedule_failure_does_not_block_remaining_schemas(self) -> None:
        source = self._make_source()
        row_a = self._make_discovered_row(source, "raw_a")
        row_b = self._make_discovered_row(source, "raw_b")
        source_schemas = {name: self._source_schema(name) for name in ["raw_a", "raw_b"]}

        def _fail_for_raw_a(schema, **kwargs):
            if schema.name == "raw_a":
                raise Exception("temporal unavailable")

        with patch(_SCHEDULE_FN, side_effect=_fail_for_raw_a):
            enabled = auto_enable_new_schemas(source, ["raw_a", "raw_b"], source_schemas)

        assert enabled == ["raw_b"]
        row_a.refresh_from_db()
        row_b.refresh_from_db()
        # raw_a's schedule failed, so it rolls back to the untouched discovery state and a later
        # pass can retry it; raw_b is unaffected and stays fully enabled.
        assert row_a.should_sync is False
        assert row_a.sync_type is None
        assert row_b.should_sync is True

    def test_schedule_failure_rollback_lets_next_pass_retry(self) -> None:
        source = self._make_source()
        row = self._make_discovered_row(source, "raw_events")
        source_schemas = {"raw_events": self._source_schema("raw_events")}

        with patch(_SCHEDULE_FN, side_effect=Exception("temporal unavailable")):
            assert auto_enable_new_schemas(source, ["raw_events"], source_schemas) == []
        after_failure = ExternalDataSchema.objects.get(id=row.id)
        assert after_failure.should_sync is False
        assert after_failure.sync_type is None

        # Temporal recovered: the rolled-back row is still an eligible candidate, so it enables now.
        with patch(_SCHEDULE_FN) as mock_schedule:
            assert auto_enable_new_schemas(source, ["raw_events"], source_schemas) == ["raw_events"]
        after_retry = ExternalDataSchema.objects.get(id=row.id)
        assert after_retry.should_sync is True
        assert after_retry.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
        mock_schedule.assert_called_once()
