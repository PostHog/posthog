import pytest
from unittest.mock import patch

from posthog.models import Organization, Team

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import calculate_table_size as calc
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size import (
    CalculateTableSizeActivityInputs,
    calculate_table_size_activity,
)


def _team() -> Team:
    return Team.objects.create(organization=Organization.objects.create(name="org"), name="t")


def _schema_table_job(team: Team) -> tuple[ExternalDataSchema, DataWarehouseTable, ExternalDataJob]:
    table = DataWarehouseTable(
        name="stripe_charge",
        format="Parquet",
        team=team,
        url_pattern="https://posthog-owned.example/team/stripe_charge",
    )
    table.save(internally_computed_url_pattern=True)
    source = ExternalDataSource.objects.create(source_id="src", connection_id="conn", team=team, source_type="Stripe")
    schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source, table=table)
    job = ExternalDataJob.objects.create(
        team=team, pipeline=source, schema=schema, status=ExternalDataJob.Status.COMPLETED
    )
    return schema, table, job


# transaction=True: the activity calls close_old_connections(), which breaks the atomic wrapper
# a plain django_db test relies on for rollback (same reason test_compute_table_statistics.py's
# activity-level test class uses it).
@pytest.mark.django_db(transaction=True)
class TestCalculateTableSizeActivity:
    def test_survives_a_concurrent_url_pattern_change_on_a_credential_less_table(self) -> None:
        # This activity only ever intends to update size_in_s3_mib. It loads the table before
        # get_size_of_folder() (an S3 listing that can take a while), so a sync elsewhere in the
        # same window can legitimately rewrite the table's url_pattern in the DB before this
        # activity's own save runs. An unscoped save() here used to compare this stale in-memory
        # url_pattern against the row's now-current DB value and reject the save as a
        # client-supplied URL change, even though nothing about this activity touches url_pattern.
        team = _team()
        schema, table, job = _schema_table_job(team)

        def _slow_listing(_folder: str) -> float:
            DataWarehouseTable.objects.filter(pk=table.pk).update(
                url_pattern="https://posthog-owned.example/team/stripe_charge_repartitioned"
            )
            return 12.5

        with patch.object(calc, "get_size_of_folder", side_effect=_slow_listing):
            calculate_table_size_activity(
                CalculateTableSizeActivityInputs(team_id=team.id, schema_id=str(schema.id), job_id=str(job.id))
            )

        table.refresh_from_db()
        assert table.size_in_s3_mib == 12.5
        assert table.url_pattern == "https://posthog-owned.example/team/stripe_charge_repartitioned"
