import pytest
from unittest.mock import patch

from django.core.management import call_command

import deltalake

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def team():
    return create_team(organization=create_organization("test org"))


def _schema_with_table(team, *, stored_row_count: int, latest_sync_rows: int) -> DataWarehouseTable:
    source = ExternalDataSource.objects.create(team=team, source_type="Postgres", job_inputs={})
    table = DataWarehouseTable.objects.create(
        name="postgres_orders",
        format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        url_pattern="s3://bucket/orders/*.parquet",
        team=team,
        row_count=stored_row_count,
        external_data_source=source,
    )
    schema = ExternalDataSchema.objects.create(
        name="orders", team=team, source=source, table=table, sync_type=ExternalDataSchema.SyncType.FULL_REFRESH
    )
    ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.COMPLETED,
        rows_synced=latest_sync_rows,
    )
    return table


@patch.object(deltalake.DeltaTable, "is_deltatable", return_value=False)
class TestRecountWarehouseTableRows:
    @pytest.mark.parametrize(
        "live_run,stored_row_count,latest_sync_rows,expected_row_count",
        [
            pytest.param(True, 200, 1_200, 1_500, id="below_latest_sync"),
            pytest.param(True, 5_000, 1_200, 5_000, id="at_or_above_latest_sync"),
            pytest.param(False, 200, 1_200, 200, id="dry_run"),
        ],
    )
    def test_recounts_only_tables_below_their_latest_sync(
        self, _is_deltatable, team, live_run, stored_row_count, latest_sync_rows, expected_row_count
    ):
        table = _schema_with_table(team, stored_row_count=stored_row_count, latest_sync_rows=latest_sync_rows)

        with patch.object(DataWarehouseTable, "get_count", return_value=1_500):
            call_command("recount_warehouse_table_rows", live_run=live_run)

        table.refresh_from_db()
        assert table.row_count == expected_row_count

    def test_keeps_the_count_a_sync_stored_during_the_recount(self, _is_deltatable, team):
        table = _schema_with_table(team, stored_row_count=200, latest_sync_rows=1_200)

        def a_sync_finishes_during_the_count() -> int:
            DataWarehouseTable.objects.filter(id=table.id).update(row_count=1_800)
            return 1_500

        with patch.object(DataWarehouseTable, "get_count", side_effect=a_sync_finishes_during_the_count):
            call_command("recount_warehouse_table_rows", live_run=True)

        table.refresh_from_db()
        assert table.row_count == 1_800
