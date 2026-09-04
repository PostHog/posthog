import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySyncActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.person_property_sync_job import (
    sync_warehouse_person_properties_activity,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.person_property_sync_job"


class TestSyncWarehousePersonPropertiesActivityCapturesFailureContext:
    """A failed run is only attributable to a source/schema in error tracking if the captured
    exception carries that context; a bare capture_exception(e) loses it."""

    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.record_failed_runs", new_callable=AsyncMock)
    @patch(f"{MODULE}.record_started_runs", new_callable=AsyncMock)
    @patch(f"{MODULE}.run_person_property_sync", new_callable=AsyncMock)
    @patch(f"{MODULE}.Heartbeater")
    async def test_capture_exception_receives_source_and_schema_context(
        self,
        mock_heartbeater_cls: MagicMock,
        mock_run_sync: AsyncMock,
        _mock_record_started: AsyncMock,
        _mock_record_failed: AsyncMock,
        mock_capture_exception: MagicMock,
    ) -> None:
        mock_heartbeater_cls.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_heartbeater_cls.return_value.__aexit__ = AsyncMock(return_value=None)
        error = ConnectionError("failed to connect to all addresses")
        mock_run_sync.side_effect = error

        inputs = PersonPropertySyncActivityInputs(
            team_id=1,
            schema_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            job_id="job-1",
            source_type="Stripe",
            schema_name="public.charges",
            last_synced_at=None,
        )

        with pytest.raises(ConnectionError):
            await ActivityEnvironment().run(sync_warehouse_person_properties_activity, inputs)

        mock_capture_exception.assert_called_once_with(error, inputs.properties_to_log)
        captured_properties = mock_capture_exception.call_args[0][1]
        assert captured_properties["source_type"] == "Stripe"
        assert captured_properties["schema_name"] == "public.charges"
