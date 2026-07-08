import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team

from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.models import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size import (
    CalculateTableSizeActivityInputs,
    calculate_table_size_activity,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
]


def _setup() -> tuple[Team, ExternalDataSchema, ExternalDataJob]:
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org, name="Test Team")
    source = ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        status="running",
        source_type="Stripe",
    )
    credential = DataWarehouseCredential.objects.create(access_key="x", access_secret="y", team=team)
    table = DataWarehouseTable.objects.create(
        name="charge",
        format="Parquet",
        team=team,
        external_data_source=source,
        external_data_source_id=source.id,
        credential=credential,
        url_pattern="https://bucket.s3/data/*",
        columns={},
    )
    schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source, table=table)
    job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=29,
    )
    return team, schema, job


def test_calculate_table_size_does_not_clobber_concurrent_completion():
    """Regression: the activity reads the job while it is RUNNING, then saves after a
    slow S3 size lookup. In V3 the standalone consumer can mark the job COMPLETED in
    that window. A full save would rewind status to RUNNING (and clear finished_at);
    the scoped save must leave status/finished_at intact while still writing
    storage_delta_mib."""
    team, schema, job = _setup()

    original_save = ExternalDataJob.save
    completed_at = datetime(2026, 5, 29, 2, 57, 8, tzinfo=UTC)

    def save_with_concurrent_completion(self, *args, **kwargs):
        # Simulate the consumer completing the job between the activity's read and its save.
        ExternalDataJob.objects.filter(id=self.id).update(
            status=ExternalDataJob.Status.COMPLETED, finished_at=completed_at
        )
        return original_save(self, *args, **kwargs)

    with (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size.get_size_of_folder",
            return_value=1.0,
        ),
        patch.object(ExternalDataJob, "save", autospec=True, side_effect=save_with_concurrent_completion),
    ):
        calculate_table_size_activity(
            CalculateTableSizeActivityInputs(team_id=team.pk, schema_id=str(schema.id), job_id=str(job.id))
        )

    refreshed = ExternalDataJob.objects.get(id=job.id)
    assert refreshed.status == ExternalDataJob.Status.COMPLETED
    assert refreshed.finished_at == completed_at
    assert refreshed.storage_delta_mib == 1.0
