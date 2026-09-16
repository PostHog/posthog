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

    def test_dry_run_changes_nothing(self, team):
        schema = _create_full_refresh_schema(team)

        with patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1758000000):
            call_command("switch_schemas_to_declared_cursor", source_type="Zendesk", schema_name="tickets")

        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH
