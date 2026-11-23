import uuid
import tempfile
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import deltalake
from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.team import Team

from products.warehouse_sources.backend.facade.contracts import LegacyHistoryTableError
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    HISTORY_SEED_PENDING_KEY,
    INCREMENTAL_HISTORY_KEY,
    ExternalDataSchema,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import HISTORY_NAMING
from products.warehouse_sources.backend.temporal.data_imports.cdc.companion_jobs import COMPANION_RUN_SUFFIX
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import HistoryTableNameTakenError
from products.warehouse_sources.backend.temporal.data_imports.incremental_history import (
    IncrementalHistoryUnavailableError,
    attach_history_lanes,
    finalize_history_lane,
    registered_history_columns,
    stage_history_batch,
    stamp_history_batch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta import history_upsert
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_upsert import (
    STAGED_BATCH_COLUMN,
    STAGED_ROW_COLUMN,
    HistoryFinalizeResult,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

_TS = pa.timestamp("us", tz="UTC")
_TRACKED_SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def _schema(mode: str, *, chose_history: bool = True) -> ExternalDataSchema:
    return ExternalDataSchema(
        name="orders",
        team=Team(id=1, organization_id=uuid.uuid4()),
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


_MODULE = "products.warehouse_sources.backend.temporal.data_imports.incremental_history"


@pytest.fixture(autouse=True)
def _flag_on():
    with patch(f"{_MODULE}.is_incremental_history_enabled_for_team", return_value=True) as flag:
        yield flag


def _attach(schema: ExternalDataSchema, response: SourceResponse, *, destination_ids: list[str] | None = None) -> None:
    with patch(f"{_MODULE}.incremental_history_naming", return_value=HISTORY_NAMING):
        attach_history_lanes(schema, response, destination_ids=destination_ids or [])


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

    def test_turning_the_flag_off_stops_the_history_lane(self, _flag_on: MagicMock) -> None:
        _flag_on.return_value = False
        response = _response()

        _attach(_schema("both"), response)

        assert response.lanes is None
        with pytest.raises(IncrementalHistoryUnavailableError, match="turned off"):
            _attach(_schema("cdc_only"), _response())

    @parameterized.expand([("no_key_anywhere", None, True), ("key_saved_on_the_schema", ["id"], False)])
    def test_a_run_without_a_resolvable_primary_key_fails(
        self, _name: str, saved_key: list[str] | None, fails: bool
    ) -> None:
        schema = _schema("both")
        schema.sync_type_config["primary_key_columns"] = saved_key
        response = _response()
        response.primary_keys = None

        if fails:
            with pytest.raises(IncrementalHistoryUnavailableError, match="primary key"):
                _attach(schema, response)
        else:
            _attach(schema, response)
            assert response.lanes is not None

    @parameterized.expand(
        [
            ("legacy_history_table", LegacyHistoryTableError("legacy")),
            ("name_taken", HistoryTableNameTakenError("taken")),
        ]
    )
    def test_a_history_table_the_run_cannot_write_fails_as_non_retryable(self, _name: str, error: Exception) -> None:
        with patch(f"{_MODULE}.incremental_history_naming", side_effect=error):
            with pytest.raises(IncrementalHistoryUnavailableError):
                attach_history_lanes(_schema("both"), _response())

    @parameterized.expand(
        [
            ("not_to_the_warehouse", "both", False, [], "warehouse"),
            ("history_only_to_another_destination_too", "cdc_only", True, ["s3-destination"], "other destinations"),
        ]
    )
    def test_a_run_whose_destinations_cannot_take_the_history_table_fails(
        self, _name: str, mode: str, to_warehouse: bool, external: list[str], match: str
    ) -> None:
        with (
            patch(f"{_MODULE}.includes_the_warehouse", return_value=to_warehouse),
            patch(f"{_MODULE}.external_destination_ids_for", return_value=external),
        ):
            with pytest.raises(IncrementalHistoryUnavailableError, match=match):
                _attach(_schema(mode), _response(), destination_ids=["warehouse", *external])


class TestRegisteredHistoryColumns:
    @parameterized.expand(
        [
            ("unselected_column_is_hidden", ["name"], ["id", "name", "updated_at", "_ph_valid_from", "_ph_valid_to"]),
            (
                "no_selection_keeps_every_column",
                None,
                ["id", "name", "email", "updated_at", "_ph_valid_from", "_ph_valid_to"],
            ),
            (
                "capture_columns_stay",
                ["name"],
                ["id", "name", "updated_at", "_ph_valid_from", "_ph_valid_to", "_ph_deleted", "_ph_cdc_op"],
                ("_ph_deleted", "_ph_cdc_op"),
            ),
        ]
    )
    def test_keeps_the_synced_key_cursor_and_validity_columns(
        self, _name: str, enabled_columns: list[str] | None, expected: list[str], extra: tuple[str, ...] = ()
    ) -> None:
        columns = dict.fromkeys(
            ("id", "name", "email", "updated_at", "_ph_valid_from", "_ph_valid_to", *extra), "String"
        )

        assert list(registered_history_columns(columns, enabled_columns, ["id"], "updated_at")) == expected


def _stamp(batch: pa.Table) -> pa.Table:
    return stamp_history_batch(
        batch, schema_name="orders", cursor="updated_at", naming=HISTORY_NAMING, tracked_since=_TRACKED_SINCE
    )


class TestStampHistoryBatch:
    @parameterized.expand(
        [
            (
                "timestamp_with_null",
                pa.array([datetime(2026, 1, 2, tzinfo=UTC), None], _TS),
                [datetime(2026, 1, 2, tzinfo=UTC), _TRACKED_SINCE],
            ),
            ("naive_timestamp", pa.array([datetime(2026, 1, 2, 3)]), [datetime(2026, 1, 2, 3, tzinfo=UTC)]),
            ("text_without_offset", pa.array(["2026-01-02T03:04:05"]), [datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)]),
        ]
    )
    def test_valid_from_is_the_cursor_in_utc(self, _name: str, cursor: pa.Array, expected: list[datetime]) -> None:
        stamped = _stamp(pa.table({"updated_at": cursor}))

        assert stamped.column("_ph_valid_from").to_pylist() == expected

    @parameterized.expand(
        [
            # Some sources declare epoch seconds as a date and time; a cast reads them as microseconds in 1970.
            ("epoch_seconds", pa.array([1700000000]), "int64"),
            ("date_only", pa.array([date(2026, 1, 2)]), "date32"),
            ("unreadable_text", pa.array(["Mon, 01 Jan 2024 00:00:00 GMT"]), "updated_at"),
        ]
    )
    def test_a_cursor_without_a_readable_date_and_time_fails_the_run(
        self, _name: str, cursor: pa.Array, match: str
    ) -> None:
        with pytest.raises(IncrementalHistoryUnavailableError, match=match):
            _stamp(pa.table({"updated_at": cursor}))

    @parameterized.expand([(STAGED_ROW_COLUMN,), (STAGED_BATCH_COLUMN,), ("_ph_valid_to",)])
    def test_a_source_column_named_like_a_history_column_fails_the_run(self, column: str) -> None:
        batch = pa.table({"updated_at": pa.array([datetime(2026, 1, 2)]), column: pa.array([1])})

        with pytest.raises(IncrementalHistoryUnavailableError, match=column):
            _stamp(batch)


class TestHistoryLaneWrites(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            patch.object(DeltaTableRef, "_get_delta_table_uri", autospec=True, side_effect=_local_uri(self.root))
        )
        self.enterContext(patch.object(DeltaTableRef, "_get_credentials", return_value={}))
        source = ExternalDataSource.objects.create(team=self.team)
        self.schema = ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="orders",
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "updated_at",
                "incremental_field_type": "datetime",
                "cdc_table_mode": "both",
                INCREMENTAL_HISTORY_KEY: True,
            },
        )
        self.job = ExternalDataJob.objects.create(
            team=self.team, pipeline=source, schema=self.schema, status=ExternalDataJob.Status.RUNNING, rows_synced=2
        )
        self.history = DeltaTableRef(resource_name="orders_history", job=self.job, logger=make_logger())

    def test_staged_batches_become_versions_at_finalize(self) -> None:
        assert self._finalize(0) is None

        # The second batch re-reads key 1 inside the lookback window.
        for index, rows in enumerate([[(1, "a", _JAN)], [(1, "a", _JAN), (2, "b", _FEB)]]):
            self._stage(rows, batch_index=index)
        result = self._finalize(1)

        assert self._history_rows() == [(1, "a", _JAN, None, "current"), (2, "b", _FEB, None, "current")]
        assert result is not None and result.staged_rows == 3

    @parameterized.expand(
        [
            ("history_rows_bill", True, 2 + 3, False),
            ("history_rows_free", False, 2, False),
            ("renamed_schema_keeps_its_folder", True, 2 + 3, True),
        ]
    )
    def test_a_seed_starts_the_history_from_the_main_table_as_it_was_before_the_run(
        self, _name: str, billable: bool, rows_synced: int, renamed: bool
    ) -> None:
        self.job.billable = billable
        self.job.save()
        if renamed:
            self.schema.name = "public.orders"
            self.schema.s3_folder_name = "orders"
        requested_at = "2026-10-05T00:00:00+00:00"
        self.schema.sync_type_config[HISTORY_SEED_PENDING_KEY] = requested_at
        self.schema.save()
        self._write_main([(1, "a", _JAN), (2, "b", _FEB), (3, "c", None)], run_uuid="earlier-run")
        # A partitioned write tags only its last merge.
        self._write_main([(2, "b2", _MAR)], run_uuid=None)
        self._write_main([(1, "a2", _MAR)], run_uuid="run")
        self._stage([(1, "a2", _MAR), (2, "b2", _MAR)], batch_index=0)

        with patch.object(history_upsert, "finalize", side_effect=RuntimeError("lost the loader")):
            with pytest.raises(RuntimeError):
                self._finalize(0)
        result = self._finalize(0)

        expected = [
            (1, "a", _JAN, _MAR, "2026-03"),
            (1, "a2", _MAR, None, "current"),
            (2, "b", _FEB, _MAR, "2026-03"),
            (2, "b2", _MAR, None, "current"),
            (3, "c", datetime.fromisoformat(requested_at), None, "current"),
        ]
        assert self._history_rows() == expected
        assert result is not None and result.staged_rows == 5
        assert PARTITION_KEY not in deltalake.DeltaTable(str(self.root / "orders_history")).schema().to_arrow().names
        self.schema.refresh_from_db()
        assert HISTORY_SEED_PENDING_KEY not in self.schema.sync_type_config
        self.job.refresh_from_db()
        assert self.job.rows_synced == rows_synced

    def _write_main(self, rows: Sequence[tuple[int, str, datetime | None]], *, run_uuid: str | None) -> None:
        table = _rows(rows).append_column(PARTITION_KEY, pa.array(["p"] * len(rows)))
        deltalake.write_deltalake(
            str(self.root / "orders"),
            table,
            mode="append",
            commit_properties=deltalake.CommitProperties(
                custom_metadata={"run_uuid": run_uuid, "batch_index": "0"} if run_uuid else None
            ),
        )

    def _stage(self, rows: Sequence[tuple[int, str, datetime | None]], *, batch_index: int) -> None:
        batch = _rows(rows)
        batch = batch.append_column("_ph_valid_from", batch.column("updated_at"))
        async_to_sync(stage_history_batch)(
            self.history, batch, primary_keys=["id"], run_uuid=_HISTORY_RUN, batch_index=batch_index
        )

    def _finalize(self, batch_index: int) -> HistoryFinalizeResult | None:
        schema = ExternalDataSchema.objects.get(id=self.schema.id)
        return async_to_sync(finalize_history_lane)(
            self.history, ["id"], schema=schema, run_uuid=_HISTORY_RUN, batch_index=batch_index
        )

    def _history_rows(self) -> list[tuple[Any, ...]]:
        rows = deltalake.DeltaTable(str(self.root / "orders_history")).to_pyarrow_table().to_pylist()
        return sorted(
            (r["id"], r["name"], r["_ph_valid_from"], r["_ph_valid_to"], r["_ph_history_partition"]) for r in rows
        )


_HISTORY_RUN = f"run{COMPANION_RUN_SUFFIX}"
_JAN, _FEB, _MAR = (datetime(2026, month, 1, tzinfo=UTC) for month in (1, 2, 3))


def _rows(rows: Sequence[tuple[int, str, datetime | None]]) -> pa.Table:
    return pa.table(
        {
            "id": pa.array([key for key, _, _ in rows], pa.int64()),
            "name": [name for _, name, _ in rows],
            "updated_at": pa.array([at for _, _, at in rows], _TS),
        }
    )


def _local_uri(root: Path) -> Any:
    async def _uri(ref: DeltaTableRef) -> str:
        return str(root / ref.resource_name)

    return _uri
