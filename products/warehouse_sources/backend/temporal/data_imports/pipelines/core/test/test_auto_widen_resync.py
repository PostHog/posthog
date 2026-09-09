import uuid
import datetime as dt
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

import pyarrow as pa

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core import auto_widen_resync
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    SchemaColumnTypeChangedException,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.auto_widen_resync import (
    COLUMN_TYPE_WIDENED_KEY,
    COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY,
    maybe_schedule_auto_widen_resync,
)

_STORED_INT64 = pa.int64()
_INCOMING_FLOAT64 = pa.float64()


def _widening_error(
    column_name: str | None = "total_cost",
    stored_type: pa.DataType | None = _STORED_INT64,
    incoming_type: pa.DataType | None = _INCOMING_FLOAT64,
) -> SchemaColumnTypeChangedException:
    return SchemaColumnTypeChangedException(
        "Source column type changed: 'total_cost' has values that no longer fit its stored type int64 "
        "(incoming data is now double). Reset and fully re-sync this table to adopt the new type.",
        column_name=column_name,
        stored_type=stored_type,
        incoming_type=incoming_type,
    )


class TestMaybeScheduleAutoWidenResync(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=self.team, source_type="Postgres"
        )
        self.schema = ExternalDataSchema.objects.create(
            name="orders", team=self.team, source=self.source, sync_type_config={}
        )
        self.job = ExternalDataJob.objects.create(
            team=self.team, pipeline=self.source, schema=self.schema, status=ExternalDataJob.Status.RUNNING
        )
        capture_patcher = patch.object(auto_widen_resync.posthoganalytics, "capture")
        self.capture_mock = capture_patcher.start()
        self.addCleanup(capture_patcher.stop)

    def _call(self, error: SchemaColumnTypeChangedException, flag_enabled: bool = True) -> str | None:
        with patch.object(auto_widen_resync, "is_auto_widen_resync_enabled", return_value=flag_enabled):
            return maybe_schedule_auto_widen_resync(self.schema, self.job, error)

    def _persisted_config(self) -> dict[str, Any]:
        self.schema.refresh_from_db()
        return self.schema.sync_type_config or {}

    def test_safe_widening_stamps_reset_and_marker(self) -> None:
        message = self._call(_widening_error())

        assert message is not None
        assert message.startswith("Source column type changed")
        assert "No action is needed" in message

        config = self._persisted_config()
        assert config["reset_pipeline"] is True
        marker = config[COLUMN_TYPE_WIDENED_KEY]
        assert marker["column"] == "total_cost"
        assert marker["stored_type"] == "int64"
        assert marker["incoming_type"] == "double"
        assert dt.datetime.fromisoformat(marker["detected_at"]).tzinfo is not None
        assert config[COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY] == marker["detected_at"]

    def test_flag_off_leaves_schema_untouched(self) -> None:
        assert self._call(_widening_error(), flag_enabled=False) is None
        assert self._persisted_config() == {}

    def test_unsafe_transitions_do_not_stamp(self) -> None:
        for error in (
            _widening_error(column_name=None, stored_type=None, incoming_type=None),
            _widening_error(incoming_type=pa.string()),
            _widening_error(stored_type=pa.decimal128(10, 2)),
        ):
            assert self._call(error) is None
        assert self._persisted_config() == {}

    def test_cooldown_blocks_second_stamp(self) -> None:
        recent = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat()
        self.schema.sync_type_config = {COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY: recent}
        self.schema.save()

        assert self._call(_widening_error()) is None

        config = self._persisted_config()
        assert "reset_pipeline" not in config
        assert COLUMN_TYPE_WIDENED_KEY not in config

    def test_cooldown_expired_allows_stamp(self) -> None:
        old = (dt.datetime.now(dt.UTC) - dt.timedelta(days=8)).isoformat()
        self.schema.sync_type_config = {COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY: old}
        self.schema.save()

        assert self._call(_widening_error()) is not None

        config = self._persisted_config()
        assert config["reset_pipeline"] is True
        assert config[COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY] != old

    def test_cdc_streaming_schema_is_skipped(self) -> None:
        self.schema.sync_type = ExternalDataSchema.SyncType.CDC
        self.schema.sync_type_config = {"cdc_mode": "streaming"}
        self.schema.save()

        assert self._call(_widening_error()) is None
        assert self._persisted_config() == {"cdc_mode": "streaming"}

    def test_webhook_schema_is_skipped(self) -> None:
        self.schema.sync_type = ExternalDataSchema.SyncType.WEBHOOK
        self.schema.save()

        assert self._call(_widening_error()) is None
        assert self._persisted_config() == {}

    def test_internal_failure_returns_none_instead_of_raising(self) -> None:
        with patch(
            "products.warehouse_sources.backend.models.external_data_schema.update_sync_type_config_keys",
            side_effect=RuntimeError("db down"),
        ):
            assert self._call(_widening_error()) is None

    def test_reset_consumes_marker_and_keeps_cooldown(self) -> None:
        stamped_at = dt.datetime.now(dt.UTC).isoformat()
        self.schema.sync_type_config = {
            "reset_pipeline": True,
            COLUMN_TYPE_WIDENED_KEY: {"column": "total_cost", "detected_at": stamped_at},
            COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY: stamped_at,
        }
        self.schema.save()

        self.schema.update_sync_type_config_for_reset_pipeline()

        config = self._persisted_config()
        assert "reset_pipeline" not in config
        assert COLUMN_TYPE_WIDENED_KEY not in config
        assert config[COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY] == stamped_at
