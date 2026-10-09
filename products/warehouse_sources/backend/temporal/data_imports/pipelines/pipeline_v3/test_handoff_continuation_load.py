import shutil
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import deltalake

from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.models import external_data_schema as schema_models
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    staged_handoff_resume_point,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline import PipelineV3
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.table_rebuild import TableRebuildRun
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportJobModels,
)

_PIPELINE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline"
_EXTRACT = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract"
_TABLE_REBUILD = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.table_rebuild"
_PRODUCER = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer"
_WORKFLOW_RUN_ID = "wfrun-abc"
_PAGE_ROWS = 4

Row = tuple[int, int]


def _logger() -> MagicMock:
    logger = MagicMock()
    for name in ("adebug", "ainfo", "awarning", "aerror", "aexception"):
        setattr(logger, name, AsyncMock())
    return logger


def _passthrough_pool(fn):
    async def call(*args, **kwargs):
        return fn(*args, **kwargs)

    return call


class _Staging:
    """Stands in for the batch store: keeps every staged batch by its path."""

    def __init__(self) -> None:
        self.tables: dict[str, pa.Table] = {}

    def writer(self, run_uuid: str) -> MagicMock:
        def write_batch(table: pa.Table, index: int) -> BatchWriteResult:
            path = f"s3://staging/{run_uuid}/{index}.parquet"
            self.tables[path] = table
            return BatchWriteResult(s3_path=path, row_count=table.num_rows, byte_size=1, batch_index=index)

        return MagicMock(
            write_batch=MagicMock(side_effect=write_batch),
            get_run_uuid=MagicMock(return_value=run_uuid),
            write_schema=MagicMock(return_value="schema.json"),
            get_data_folder=MagicMock(return_value="s3://staging"),
            get_base_folder=MagicMock(return_value="s3://staging"),
        )


@dataclass(frozen=False)
class _Import:
    """One schema, its source rows, its queue and its table on local disk."""

    table_uri: str
    source_rows: list[Row]
    schema: ExternalDataSchema = field(init=False)
    staging: _Staging = field(default_factory=_Staging)
    queue: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 0
    pages_read: int = 0

    def __post_init__(self) -> None:
        self.schema = ExternalDataSchema(
            name="orders",
            team_id=1,
            sync_type="incremental",
            sync_type_config={"incremental_field": "n", "incremental_field_type": "integer"},
        )

    def _update_config(self, schema_id, team_id, *, updates=None, removes=None, mutate=None, **_kwargs):
        config = dict(self.schema.sync_type_config)
        config.update(updates or {})
        for key in removes or []:
            config.pop(key, None)
        if mutate is not None:
            mutate(config)
        self.schema.sync_type_config = config
        return config

    def _source(self, read_after: int | None) -> SourceResponse:
        self.pages_read = 0
        rows = sorted(
            (row for row in self.source_rows if read_after is None or row[1] > read_after), key=lambda row: row[1]
        )

        def items() -> Iterator[pa.Table]:
            for start in range(0, len(rows), _PAGE_ROWS):
                page = rows[start : start + _PAGE_ROWS]
                self.pages_read += 1
                yield pa.table({"id": [row[0] for row in page], "n": [row[1] for row in page]})

        return SourceResponse(name="orders", items=items, primary_keys=["id"], chunk_size=_PAGE_ROWS)

    async def run_attempt(self, *, shut_down_after_pages: int | None, reset_pipeline: bool = False) -> bool:
        """Run one execution of the import the way the activity builds it. Returns whether it handed off."""
        self.attempts += 1
        attempt = self.attempts
        reset_pipeline = reset_pipeline and self.schema.sync_type_config.get("reset_pipeline") is True
        stored_watermark = None if reset_pipeline else self.schema.sync_type_config.get("incremental_field_last_value")
        checkpoints_allowed = not reset_pipeline and self.schema.is_incremental
        resume_point = (
            staged_handoff_resume_point(self.schema.sync_type_config, _WORKFLOW_RUN_ID) if checkpoints_allowed else None
        )
        resumed_run_uuid, resumed_value = resume_point if resume_point and resume_point[1] is not None else (None, None)

        monitor = MagicMock()

        def is_shutdown() -> bool:
            return shut_down_after_pages is not None and self.pages_read >= shut_down_after_pages

        def raise_if_shutdown() -> None:
            if is_shutdown():
                raise WorkerShuttingDownError("id", "type", "queue", 1, "workflow", "workflow_type")

        monitor.is_worker_shutdown.side_effect = is_shutdown
        monitor.raise_if_is_worker_shutdown.side_effect = raise_if_shutdown

        table_ref = MagicMock(is_first_sync=False)

        async def reset_table(reset: bool, should_resume: bool, *_args: Any, **_kwargs: Any) -> None:
            if reset and not should_resume:
                shutil.rmtree(self.table_uri, ignore_errors=True)
                table_ref.is_first_sync = True
                self._update_config(None, None, removes=["reset_pipeline", "incremental_field_last_value"])

        with ExitStack() as stack:
            stack.enter_context(patch(f"{_PIPELINE}.current_import_attempt", return_value=attempt))
            stack.enter_context(patch(f"{_PIPELINE}.current_workflow_id", return_value="wf-1"))
            stack.enter_context(patch(f"{_PIPELINE}.current_workflow_run_id", return_value=_WORKFLOW_RUN_ID))
            stack.enter_context(
                patch(
                    f"{_PIPELINE}.S3BatchWriter",
                    side_effect=lambda _l, _j, _s, run_uuid, **_k: self.staging.writer(run_uuid),
                )
            )
            stack.enter_context(patch(f"{_PIPELINE}.DeltaTableRef", return_value=table_ref))
            stack.enter_context(patch(f"{_PIPELINE}.build_pipeline_sinks")).return_value = MagicMock(
                clear=AsyncMock(),
                stage_chunk=AsyncMock(),
                cdp_producer=MagicMock(should_run=AsyncMock(return_value=False)),
            )
            conn = MagicMock()
            conn.execute.side_effect = lambda query, params=None: (
                self.queue.append(dict(params)) if "INSERT INTO" in query and "VALUES" in query else None
            )
            stack.enter_context(patch(f"{_PRODUCER}._connect_with_retry", return_value=conn))
            stack.enter_context(patch(f"{_PRODUCER}.BatchQueue.supersede_other_runs", return_value=0))
            stack.enter_context(patch.object(schema_models, "update_sync_type_config_keys", self._update_config))
            stack.enter_context(patch(f"{_PIPELINE}.update_sync_type_config_keys", self._update_config))
            stack.enter_context(patch(f"{_TABLE_REBUILD}.update_sync_type_config_keys", self._update_config))
            for module in (_PIPELINE, _EXTRACT):
                stack.enter_context(patch(f"{module}.database_sync_to_async_pool", new=_passthrough_pool))
            for name in (
                "reset_rows_synced_if_needed",
                "setup_row_tracking_with_billing_check",
                "persist_primary_keys",
                "handle_corrupted_delta_log",
                "update_row_tracking_after_batch",
            ):
                stack.enter_context(patch(f"{_PIPELINE}.{name}", new_callable=AsyncMock))
            stack.enter_context(patch(f"{_PIPELINE}.handle_reset_or_full_refresh", side_effect=reset_table))
            stack.enter_context(patch(f"{_PIPELINE}.validate_incremental_sync"))
            stack.enter_context(patch(f"{_EXTRACT}.is_young_first_attempt", return_value=attempt == 1))
            stack.enter_context(patch(f"{_PIPELINE}.record_source_item_stats"))
            stack.enter_context(patch(f"{_PIPELINE}.posthoganalytics"))
            stack.enter_context(patch(f"{_PIPELINE}.DeltaMaintenance")).return_value.run_scheduled = AsyncMock()
            stack.enter_context(patch(f"{_PIPELINE}.activity")).in_activity.return_value = False

            pipeline: PipelineV3 = PipelineV3(
                source_response=self._source(resumed_value if resumed_value is not None else stored_watermark),
                logger=_logger(),
                job_id="job-1",
                reset_pipeline=reset_pipeline,
                shutdown_monitor=monitor,
                resumable_source_manager=None,
                models=ImportJobModels(
                    job=MagicMock(
                        team_id=1, workflow_run_id=_WORKFLOW_RUN_ID, id="job-1", destination_ids=[], billable=False
                    ),
                    schema=self.schema,
                    source=MagicMock(source_type="Postgres"),
                    table=self.schema.table,
                ),
                incremental_checkpoints_allowed=checkpoints_allowed,
                resumed_incremental_run_uuid=resumed_run_uuid,
                resumed_incremental_value=resumed_value,
            )
            try:
                await pipeline.run()
            except WorkerShuttingDownError:
                return True
        return False

    async def load_queue(self) -> None:
        """Load every queued batch the way the load consumer writes it."""
        seen: set[tuple[str, int]] = set()
        for row in self.queue:
            key = (row["run_uuid"], row["batch_index"])
            if key in seen or TableRebuildRun(self.schema.sync_type_config).replaces(row["run_uuid"]):
                continue
            seen.add(key)
            table_ref = DeltaTableRef(
                resource_name="orders", job=MagicMock(), logger=_logger(), is_first_sync=row["is_first_ever_sync"]
            )
            with (
                patch.object(table_ref, "_get_delta_table_uri", new=AsyncMock(return_value=self.table_uri)),
                patch.object(table_ref, "_get_credentials", new=MagicMock(return_value={})),
            ):
                await DeltaWriter(table_ref).write(
                    data=self.staging.tables[row["s3_path"]],
                    write_type="incremental" if row["sync_type"] == "incremental" else row["sync_type"],
                    should_overwrite_table=row["batch_index"] == 0 and not row["is_resume"],
                    primary_keys=["id"],
                )

    def loaded_ids(self) -> list[int]:
        ids = deltalake.DeltaTable(self.table_uri).to_pyarrow_table().column("id").to_pylist()
        return sorted(cast(list[int], ids))


def _rows(values: list[int]) -> list[Row]:
    return [(index + 1, value) for index, value in enumerate(values)]


_UNIQUE = _rows(list(range(10, 34)))
# Six rows hold 14 and five hold 20, so a page and a hand-off end inside a group of equal values.
_TIES = _rows([10, 11, 12, 14, 14, 14, 14, 14, 14, 15, 16, 20, 20, 20, 20, 20, 21, 22, 23, 24])


@pytest.mark.parametrize(
    "source_rows", [pytest.param(_UNIQUE, id="unique_values"), pytest.param(_TIES, id="equal_values")]
)
@pytest.mark.parametrize(
    "scenario, handoffs",
    [
        pytest.param("first_sync", [2], id="first_sync_one_handoff"),
        pytest.param("first_sync", [1, 1, 1], id="first_sync_handoff_on_every_page"),
        pytest.param("existing_table", [2, 2], id="existing_table_two_handoffs"),
        pytest.param("rebuild", [2, 2, 1], id="rebuild_after_reset_then_two_continuations"),
    ],
)
@pytest.mark.asyncio
async def test_a_run_that_continues_after_a_handoff_loads_each_source_row_once(
    tmp_path: Path, source_rows: list[Row], scenario: str, handoffs: list[int]
) -> None:
    run = _Import(table_uri=str(tmp_path / "orders"), source_rows=source_rows)
    if scenario != "first_sync":
        earlier_rows = [row for row in source_rows if row[1] <= source_rows[5][1]]
        deltalake.write_deltalake(
            run.table_uri, pa.table({"id": [r[0] for r in earlier_rows], "n": [r[1] for r in earlier_rows]})
        )
        run.schema.table = DataWarehouseTable(name="orders", team_id=1)
        run.schema.sync_type_config["incremental_field_last_value"] = earlier_rows[-1][1]
    if scenario == "rebuild":
        run.schema.sync_type_config["reset_pipeline"] = True

    for pages in [*handoffs, None]:
        if not await run.run_attempt(shut_down_after_pages=pages, reset_pipeline=scenario == "rebuild"):
            break
    await run.load_queue()

    assert run.loaded_ids() == [row[0] for row in source_rows]
