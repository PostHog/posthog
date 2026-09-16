import pytest
from unittest.mock import patch

from django.core.management import call_command

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def team():
    return create_team(organization=create_organization("test org"))


def _create_full_refresh_schema(
    team,
    with_table=True,
    source_type="Zendesk",
    job_inputs=None,
    api_version=None,
    schema_name="tickets",
    status=ExternalDataSchema.Status.COMPLETED,
):
    source = ExternalDataSource.objects.create(
        team=team,
        source_type=source_type,
        job_inputs=job_inputs or {"subdomain": "nibbles", "api_key": "token", "email_address": "user@example.com"},
        api_version=api_version,
    )
    table = (
        DataWarehouseTable.objects.create(
            team=team,
            name=f"{source_type.lower()}_{schema_name}",
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="https://bucket/x/*",
            external_data_source=source,
        )
        if with_table
        else None
    )
    return ExternalDataSchema.objects.create(
        name=schema_name,
        team=team,
        source=source,
        table=table,
        should_sync=True,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
        status=status,
    )


class TestSwitchSchemasToDeclaredCursor:
    def test_starts_the_cursor_from_the_rows_already_synced(self, team):
        schema = _create_full_refresh_schema(team)

        with patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1758000000):
            call_command(
                "switch_schemas_to_declared_cursor", source_type="Zendesk", schema_name="tickets", live_run=True
            )

        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
        assert schema.sync_type_config["incremental_field"] == "generated_timestamp"
        # Without this the next run restarts at the epoch and re-reads every ticket.
        assert schema.sync_type_config["incremental_field_last_value"] == 1758000000

    def test_leaves_a_schema_alone_when_it_has_no_cursor_value_to_start_from(self, team):
        schema = _create_full_refresh_schema(team, with_table=False)

        call_command("switch_schemas_to_declared_cursor", source_type="Zendesk", schema_name="tickets", live_run=True)

        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_leaves_a_schema_alone_when_its_last_sync_did_not_complete(self, team):
        schema = _create_full_refresh_schema(team, status=ExternalDataSchema.Status.FAILED)

        with patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1758000000):
            call_command(
                "switch_schemas_to_declared_cursor", source_type="Zendesk", schema_name="tickets", live_run=True
            )

        schema.refresh_from_db()
        # A run that stopped partway can leave only the newest rows, so a cursor seeded from them
        # would sit above the older rows the run never wrote.
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_reads_the_cursor_from_the_version_the_schema_is_pinned_to(self, team):
        schema = _create_full_refresh_schema(
            team,
            source_type="ShipStation",
            job_inputs={"api_key": "key", "api_secret": "secret"},
            api_version="v1",
            schema_name="shipments",
        )

        with patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1758000000):
            call_command(
                "switch_schemas_to_declared_cursor", source_type="ShipStation", schema_name="shipments", live_run=True
            )

        schema.refresh_from_db()
        # v2 shipments declare `modified_at`, a column a v1 sync cannot filter on, so the run
        # would send no cursor and re-read the whole table.
        assert schema.sync_type_config["incremental_field"] == "createDate"

    def test_appends_a_table_the_connector_cannot_merge(self, team):
        schema = _create_full_refresh_schema(
            team,
            source_type="CiscoDuo",
            job_inputs={"api_hostname": "api-x.duosecurity.example", "integration_key": "k", "secret_key": "s"},
            schema_name="administrator_logs",
        )

        with patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1758000000):
            call_command(
                "switch_schemas_to_declared_cursor",
                source_type="CiscoDuo",
                schema_name="administrator_logs",
                live_run=True,
            )

        schema.refresh_from_db()
        # These rows have no unique id, so a merge has no key to match on and every run after the
        # switch would fail once the table exists.
        assert schema.sync_type == ExternalDataSchema.SyncType.APPEND
        assert schema.sync_type_config["incremental_field"] == "timestamp"
        assert schema.sync_type_config["incremental_field_last_value"] == 1758000000

    def test_keeps_the_re_read_window_the_connector_declares(self, team):
        schema = _create_full_refresh_schema(
            team,
            source_type="Anthropic",
            job_inputs={"api_key": "token"},
            schema_name="usage_report",
        )

        with patch.object(DataWarehouseTable, "get_max_value_for_column", return_value="2026-09-01T00:00:00+00:00"):
            call_command(
                "switch_schemas_to_declared_cursor",
                source_type="Anthropic",
                schema_name="usage_report",
                live_run=True,
            )

        schema.refresh_from_db()
        # The vendor restates these buckets for a day, so without the window the cursor moves past
        # a revision and the first-imported numbers stay frozen.
        assert schema.sync_type_config["incremental_field_lookback_seconds"] == 60 * 60 * 24

    def test_seeds_from_a_cursor_the_warehouse_stores_snake_cased(self, team):
        schema = _create_full_refresh_schema(
            team,
            source_type="CultureAmp",
            job_inputs={"client_id": "id", "client_secret": "secret", "account_id": "account"},
            schema_name="performance_cycles",
        )

        def max_value(column):
            # The connector declares `processedAt`, and the warehouse holds only `processed_at`.
            return 1758000000 if column == "processed_at" else None

        with patch.object(DataWarehouseTable, "get_max_value_for_column", side_effect=max_value):
            call_command(
                "switch_schemas_to_declared_cursor",
                source_type="CultureAmp",
                schema_name="performance_cycles",
                live_run=True,
            )

        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
        # The config keeps the declared spelling, which the pipeline normalizes when it reads.
        assert schema.sync_type_config["incremental_field"] == "processedAt"
        assert schema.sync_type_config["incremental_field_last_value"] == 1758000000

    def test_one_unreadable_source_row_does_not_strand_the_rest(self, team):
        broken = _create_full_refresh_schema(team, with_table=False, job_inputs={"subdomain": "nibbles"})
        healthy = _create_full_refresh_schema(team)

        with patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1758000000):
            call_command(
                "switch_schemas_to_declared_cursor", source_type="Zendesk", schema_name="tickets", live_run=True
            )

        broken.refresh_from_db()
        healthy.refresh_from_db()
        # The selection has no order, so a row that raises must not decide whether the others run.
        assert broken.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH
        assert healthy.sync_type == ExternalDataSchema.SyncType.INCREMENTAL

    def test_dry_run_changes_nothing(self, team):
        schema = _create_full_refresh_schema(team)

        with patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1758000000):
            call_command("switch_schemas_to_declared_cursor", source_type="Zendesk", schema_name="tickets")

        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH
