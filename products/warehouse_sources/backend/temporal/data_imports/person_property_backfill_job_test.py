import uuid

import pytest
from unittest.mock import AsyncMock, patch

from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.temporal.data_imports import person_property_backfill_job as bj
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertyBackfillActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_sync import SyncResult


def _inputs(team_id: int) -> PersonPropertyBackfillActivityInputs:
    return PersonPropertyBackfillActivityInputs(
        team_id=team_id,
        schema_id=uuid.uuid4(),
        source_type="Stripe",
        schema_name="charges",
        trigger="manual",
    )


@pytest.mark.django_db(transaction=True)
class TestBackfillWarehousePersonPropertiesActivity:
    async def test_records_one_stage_per_nonzero_funnel_count(self) -> None:
        # A distinct team_id per test keeps the module-level Counter's label values from a previous
        # test run bleeding into this one's assertions.
        team_id = 900001
        result = SyncResult(sources=1, rows_read=5, changed=3, existing=0, produced=3, skipped_missing_person=1)
        with (
            patch.object(bj, "run_person_property_backfill", AsyncMock(return_value=result)),
            patch.object(bj, "record_completed_runs", AsyncMock()) as mock_record,
        ):
            returned = await ActivityEnvironment().run(
                bj.backfill_warehouse_person_properties_activity, _inputs(team_id)
            )

        assert returned == {
            "sources": 1,
            "rows_read": 5,
            "changed": 3,
            "existing": 0,
            "produced": 3,
            "skipped_missing_person": 1,
            "per_source": [],
        }
        mock_record.assert_awaited_once()

        def stage_value(stage: str) -> float:
            return bj.PERSON_PROPERTY_BACKFILL_ROWS_TOTAL.labels(team_id=str(team_id), stage=stage)._value.get()

        # Every nonzero stage got its count.
        assert stage_value("read") == 5
        assert stage_value("changed") == 3
        assert stage_value("produced") == 3
        assert stage_value("skipped_missing_person") == 1
        # A zero-count stage is skipped rather than recorded as a no-op increment, so the label
        # never appears on a backfill that didn't touch it.
        assert stage_value("existing") == 0

    async def test_read_rows_with_no_changes_still_recorded(self) -> None:
        # Regression: a backfill that reads rows but changes/produces nothing (the "no metrics but
        # logs" gap this metric exists to close) must still report the read count.
        team_id = 900002
        result = SyncResult(sources=1, rows_read=10, changed=0, existing=10, produced=0, skipped_missing_person=0)
        with (
            patch.object(bj, "run_person_property_backfill", AsyncMock(return_value=result)),
            patch.object(bj, "record_completed_runs", AsyncMock()),
        ):
            await ActivityEnvironment().run(bj.backfill_warehouse_person_properties_activity, _inputs(team_id))

        def stage_value(stage: str) -> float:
            return bj.PERSON_PROPERTY_BACKFILL_ROWS_TOTAL.labels(team_id=str(team_id), stage=stage)._value.get()

        assert stage_value("read") == 10
        assert stage_value("existing") == 10
        assert stage_value("changed") == 0
        assert stage_value("produced") == 0
