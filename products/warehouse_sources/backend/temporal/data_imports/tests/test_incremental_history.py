from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import INCREMENTAL_HISTORY_KEY, ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import HISTORY_NAMING
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCReservedColumnError
from products.warehouse_sources.backend.temporal.data_imports.incremental_history import (
    attach_history_lanes,
    finalize_history_lane,
    stage_history_batch,
    stamp_history_batch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_writer import (
    STAGED_BATCH_COLUMN,
    STAGED_ROW_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

_TS = pa.timestamp("us", tz="UTC")
_TRACKED_SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def _schema(mode: str, *, chose_history: bool = True) -> ExternalDataSchema:
    return ExternalDataSchema(
        name="orders",
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={
            "incremental_field": "updatedAt",
            "incremental_field_type": "datetime",
            "cdc_table_mode": mode,
            INCREMENTAL_HISTORY_KEY: chose_history,
        },
    )


def _response(primary_keys: list[str] | None = None) -> SourceResponse:
    return SourceResponse(name="orders", items=lambda: iter([]), primary_keys=primary_keys or ["id"])


def _attach(schema: ExternalDataSchema, response: SourceResponse) -> None:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.incremental_history.kept_history_naming",
        return_value=HISTORY_NAMING,
    ):
        attach_history_lanes(schema, response)


class TestAttachHistoryLanes:
    @parameterized.expand(
        [
            ("both", "both", True, [("orders", None, True), ("orders_history", "scd2_append", False)]),
            ("history_only", "cdc_only", True, [("orders_history", "scd2_append", True)]),
            # A schema that left CDC keeps its mode but never chose history here.
            ("mode_left_from_cdc", "both", False, None),
        ]
    )
    def test_lanes_follow_the_output_tables(
        self, _name: str, mode: str, chose_history: bool, expected: list[tuple[str, str | None, bool]] | None
    ) -> None:
        response = _response()

        _attach(_schema(mode, chose_history=chose_history), response)

        lanes = [(lane.name, lane.cdc_write_mode, lane.billable) for lane in response.lanes] if response.lanes else None
        assert lanes == expected
        assert response.name == (expected[0][0] if expected else "orders")

    @parameterized.expand([("no_key_anywhere", None, True), ("key_saved_on_the_schema", ["id"], False)])
    def test_a_run_without_a_resolvable_primary_key_fails(
        self, _name: str, saved_key: list[str] | None, fails: bool
    ) -> None:
        schema = _schema("both")
        schema.sync_type_config["primary_key_columns"] = saved_key
        response = _response()
        response.primary_keys = None

        if fails:
            with pytest.raises(ValueError, match="primary key"):
                _attach(schema, response)
        else:
            _attach(schema, response)
            assert response.lanes is not None


class TestStampHistoryBatch:
    @parameterized.expand(
        [
            ("date", pa.array([date(2026, 1, 2), None]), [datetime(2026, 1, 2, tzinfo=UTC), _TRACKED_SINCE]),
            ("naive_timestamp", pa.array([datetime(2026, 1, 2, 3)]), [datetime(2026, 1, 2, 3, tzinfo=UTC)]),
            ("text_without_offset", pa.array(["2026-01-02T03:04:05"]), [datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)]),
        ]
    )
    def test_valid_from_is_the_cursor_in_utc(self, _name: str, cursor: pa.Array, expected: list[datetime]) -> None:
        stamped = stamp_history_batch(
            pa.table({"updated_at": cursor}), cursor="updated_at", naming=HISTORY_NAMING, tracked_since=_TRACKED_SINCE
        )

        assert stamped.column("_ph_valid_from").to_pylist() == expected

    @parameterized.expand([(STAGED_ROW_COLUMN,), (STAGED_BATCH_COLUMN,), ("_ph_valid_to",)])
    def test_a_source_column_named_like_a_history_column_fails_the_batch(self, column: str) -> None:
        batch = pa.table({"updated_at": pa.array([date(2026, 1, 2)]), column: pa.array([1])})

        with pytest.raises(CDCReservedColumnError):
            stamp_history_batch(batch, cursor="updated_at", naming=HISTORY_NAMING, tracked_since=_TRACKED_SINCE)


class TestHistoryLaneWrites:
    @pytest.mark.asyncio
    async def test_staged_batches_become_versions_at_finalize(self, tmp_path: Path) -> None:
        with (
            patch.object(DeltaTableRef, "_get_delta_table_uri", autospec=True, side_effect=_local_uri(tmp_path)),
            patch.object(DeltaTableRef, "_get_credentials", return_value={}),
        ):
            table = DeltaTableRef(resource_name="orders_history", job=MagicMock(), logger=make_logger())
            assert await finalize_history_lane(table, ["id"]) is None

            def _batch(rows: list[tuple[int, datetime]]) -> pa.Table:
                cursors = pa.array([at for _, at in rows], type=_TS)
                return pa.table({"id": [key for key, _ in rows], "updated_at": cursors, "_ph_valid_from": cursors})

            first, second = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
            # The second batch re-reads key 1 inside the lookback window.
            for index, batch in enumerate([_batch([(1, first)]), _batch([(1, first), (2, second)])]):
                await stage_history_batch(table, batch, primary_keys=["id"], run_uuid="run", batch_index=index)
            result = await finalize_history_lane(table, ["id"])

        rows = deltalake.DeltaTable(str(tmp_path / "orders_history")).to_pyarrow_table().sort_by("id").to_pylist()
        assert [(r["id"], r["_ph_valid_from"], r["_ph_valid_to"], r["_ph_history_partition"]) for r in rows] == [
            (1, first, None, "current"),
            (2, second, None, "current"),
        ]
        assert result is not None and result.staged_rows == 3


def _local_uri(root: Path) -> Any:
    async def _uri(ref: DeltaTableRef) -> str:
        return str(root / ref.resource_name)

    return _uri
