import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import (
    CDC_RESET_PENDING_KEY,
    hand_reset_to_capture,
)

_API = "products.data_warehouse.backend.facade.api"
_SNAPSHOT_LANE = "products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane"


def _schema() -> MagicMock:
    schema = MagicMock()
    schema.cdc_halted = False
    schema.sync_type_config = {}
    return schema


class TestHandingAResetToCapture:
    def test_a_hand_over_that_starts_no_capture_run_still_makes_sure_capture_is_scheduled(self) -> None:
        # Capture is the only thing that finishes the reset, and the paused table schedule stops the
        # sync that handed it over from ever retrying, so a missing schedule is recreated here —
        # without its first run, which would cancel that sync while it finishes.
        schema = _schema()

        with (
            patch(f"{_API}.cdc_extraction_schedule_exists", return_value=False),
            patch(f"{_API}.sync_cdc_extraction_schedule") as sync_schedule,
            patch(f"{_API}.pause_external_data_schedule") as pause,
            patch(f"{_API}.trigger_cdc_extraction_schedule") as trigger,
            patch(f"{_SNAPSHOT_LANE}.update_sync_type_config_keys", return_value={CDC_RESET_PENDING_KEY: {}}),
        ):
            hand_reset_to_capture(schema, MagicMock(), start_capture=False)

        sync_schedule.assert_called_once_with(schema.source, create=True, trigger_immediately=False)
        pause.assert_called_once()
        trigger.assert_not_called()

    def test_a_hand_over_leaves_a_capture_schedule_that_is_already_there_alone(self) -> None:
        schema = _schema()

        with (
            patch(f"{_API}.cdc_extraction_schedule_exists", return_value=True),
            patch(f"{_API}.sync_cdc_extraction_schedule") as sync_schedule,
            patch(f"{_API}.pause_external_data_schedule") as pause,
            patch(f"{_API}.trigger_cdc_extraction_schedule") as trigger,
            patch(f"{_SNAPSHOT_LANE}.update_sync_type_config_keys", return_value={CDC_RESET_PENDING_KEY: {}}),
        ):
            hand_reset_to_capture(schema, MagicMock(), start_capture=False)

        sync_schedule.assert_not_called()
        trigger.assert_not_called()
        pause.assert_called_once()

    def test_a_capture_schedule_that_cannot_be_recreated_leaves_the_table_ticking(self) -> None:
        # Failing here loses nothing: the table's schedule still runs, and its next tick hands the
        # reset over again. Pausing it first would leave the reset pending with nothing to finish it.
        schema = _schema()

        with (
            patch(f"{_API}.cdc_extraction_schedule_exists", return_value=False),
            patch(f"{_API}.sync_cdc_extraction_schedule", side_effect=RuntimeError("temporal is down")),
            patch(f"{_API}.pause_external_data_schedule") as pause,
            patch(f"{_SNAPSHOT_LANE}.update_sync_type_config_keys") as stage,
            pytest.raises(RuntimeError),
        ):
            hand_reset_to_capture(schema, MagicMock(), start_capture=False)

        pause.assert_not_called()
        stage.assert_not_called()
