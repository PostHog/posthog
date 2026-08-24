"""Eligibility for completing a run on a negative source probe.

Every condition here exists because skipping a run that owed repair work broke something:
a repair loop that only runs on the sync path stops running at all on a schema that always
fast-returns. A dropped condition is silent until a customer notices stale state.
"""

import uuid
import datetime as dt

from freezegun import freeze_time
from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    _fast_return_eligible,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model"


def _recent() -> str:
    return (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()


def _schema(**config_overrides) -> ExternalDataSchema:
    config = {
        "incremental_field": "updated_at",
        "incremental_field_type": "datetime",
        "incremental_field_last_value": "2026-08-01T00:00:00+00:00",
        "last_full_run_at": _recent(),
    }
    config.update(config_overrides)
    return ExternalDataSchema(
        id=uuid.uuid4(),
        name="orders",
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        initial_sync_complete=True,
        sync_type_config=config,
    )


def _run(schema: ExternalDataSchema, *, enrichment=False, statistics=False, data_quality=False, flag_enabled=True):
    with (
        patch(f"{_MODULE}.data_quality_checks_needed_for", return_value=data_quality),
        patch(f"{_MODULE}.is_fast_return_enabled", return_value=flag_enabled),
    ):
        return _fast_return_eligible(
            schema=schema,
            team_id=1,
            enrichment_needed=enrichment,
            statistics_needed=statistics,
        )


class TestFastReturnEligibility:
    def test_steady_state_incremental_schema_is_eligible(self):
        assert _run(_schema()) is True

    @parameterized.expand(
        [
            ("full_refresh", ExternalDataSchema.SyncType.FULL_REFRESH),
            ("cdc", ExternalDataSchema.SyncType.CDC),
            ("xmin", ExternalDataSchema.SyncType.XMIN),
            ("webhook", ExternalDataSchema.SyncType.WEBHOOK),
        ]
    )
    def test_sync_types_without_a_queryable_cursor_are_not_eligible(self, _name: str, sync_type: str):
        schema = _schema()
        schema.sync_type = sync_type

        assert _run(schema) is False

    @parameterized.expand(
        [
            ("no_watermark", {"incremental_field_last_value": None}),
            ("reset_pending", {"reset_pipeline": True}),
            ("lookback_rereads_rows", {"incremental_field_lookback_seconds": 3600}),
            ("repartition_pending", {"repartition_pending": {"partition_mode": "md5"}}),
            ("repartition_swap", {"repartition_swap": {"state": "ready"}}),
            ("delta_revive_required", {"delta_revive_required": {"reason": "hollow"}}),
            ("never_ran_fully", {"last_full_run_at": None}),
            ("last_full_run_too_old", {"last_full_run_at": "2026-08-01T00:00:00+00:00"}),
            ("unparseable_full_run_stamp", {"last_full_run_at": "not-a-date"}),
        ]
    )
    def test_schema_state_that_blocks_eligibility(self, _name: str, config_overrides: dict):
        assert _run(_schema(**config_overrides)) is False

    @freeze_time("2026-08-24T12:00:00Z")
    def test_naive_full_run_stamp_is_not_eligible(self):
        assert _run(_schema(last_full_run_at="2026-08-24T11:00:00")) is False

    def test_incomplete_initial_sync_is_not_eligible(self):
        schema = _schema()
        schema.initial_sync_complete = False

        assert _run(schema) is False

    @parameterized.expand(
        [
            ("enrichment", {"enrichment": True}),
            ("statistics", {"statistics": True}),
            ("data_quality", {"data_quality": True}),
        ]
    )
    def test_outstanding_repair_work_blocks_eligibility(self, _name: str, gates: dict):
        assert _run(_schema(), **gates) is False

    def test_rollout_flag_off_is_not_eligible(self):
        assert _run(_schema(), flag_enabled=False) is False
