import uuid
import tempfile
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

import pyarrow as pa
import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY

_COMMAND_MODULE = "products.warehouse_sources.backend.management.commands.stage_warehouse_repartition"
_FITS = 10**12
_QUEUED = {"partition_mode": "datetime", "partition_format": "week", "partition_keys": ["created_at"]}


class TestStageWarehouseRepartition(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Three hour partitions over two days, standing in for a table split from day to hour.
        self.table_uri = f"{self.enterContext(tempfile.TemporaryDirectory())}/swaps"
        hours = ["2026-09-28T10", "2026-09-28T11", "2026-09-29T10"]
        deltalake.write_deltalake(
            self.table_uri,
            pa.table({"id": list(range(len(hours))), PARTITION_KEY: hours}),
            partition_by=PARTITION_KEY,
        )
        self.enterContext(patch(f"{_COMMAND_MODULE}.build_delta_table_uri", return_value=self.table_uri))
        self.enterContext(patch(f"{_COMMAND_MODULE}.delta_storage_options", return_value={}))

    def _schema(self, config: dict[str, Any] | None = None, **fields: Any) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Completed",
            source_type="Postgres",
        )
        return ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source=source,
            name="swaps",
            **{"should_sync": True, "sync_type": ExternalDataSchema.SyncType.INCREMENTAL, **fields},
            sync_type_config={
                "partitioning_enabled": True,
                "partition_mode": "datetime",
                "partition_format": "hour",
                "partitioning_keys": ["created_at"],
                **(config or {}),
            },
        )

    def _run(self, schemas: list[ExternalDataSchema], *, budget: int = _FITS, **options: Any) -> str:
        out = StringIO()
        with patch(f"{_COMMAND_MODULE}.target_partition_bytes", return_value=budget):
            call_command(
                "stage_warehouse_repartition",
                stdout=out,
                schema_id=[str(schema.id) for schema in schemas],
                **{"format": "day", **options},
            )
        return out.getvalue()

    def test_dry_run_reports_the_layout_without_staging(self) -> None:
        # A staged rewrite holds the table's next sync for as long as it runs, so a preview must not
        # leave a target behind.
        schema = self._schema()

        output = self._run([schema])

        assert str(schema.id) in output
        assert "3 -> 2 partitions" in output
        schema.refresh_from_db()
        assert schema.repartition_pending is None

    def test_execute_stages_the_rewrite_the_next_sync_runs(self) -> None:
        # The refused schema rides along to show that one bad table does not stop the batch.
        schema = self._schema()
        hashed = self._schema({"partition_mode": "md5", "partition_count": 4})

        self._run([hashed, schema], execute=True)

        schema.refresh_from_db()
        hashed.refresh_from_db()
        assert schema.repartition_pending == {
            "partition_mode": "datetime",
            "partition_format": "day",
            "partition_count": None,
            "partition_size": None,
            "partition_keys": ["created_at"],
            "trigger_reason": "admin",
            "attempts": 0,
        }
        assert hashed.repartition_pending is None

    @parameterized.expand(
        [
            # A partition over the budget is what makes a merge run out of memory, and the rewrite
            # itself has no size check for an operator's target.
            ("over_budget", {}, {}, {"budget": 1}),
            # A second target would replace a rewrite that is queued or already in progress.
            ("busy", {"repartition_pending": _QUEUED}, {}, {}),
            ("busy", {"repartition_swap": {"state": "ready"}}, {}, {}),
            ("not_coarser", {"partition_format": "day"}, {}, {}),
            ("not_datetime", {"partition_mode": "md5", "partition_count": 4}, {}, {}),
            ("cdc", {}, {"sync_type": ExternalDataSchema.SyncType.CDC}, {}),
            # Only a sync runs the rewrite, so a target on a paused schema would wait forever.
            ("not_syncing", {}, {"should_sync": False}, {}),
            ("no_partition_key", {"partitioning_keys": []}, {}, {}),
        ]
    )
    def test_refuses_a_rewrite_it_cannot_stage_safely(
        self, reason: str, config: dict[str, Any], fields: dict[str, Any], run_options: dict[str, Any]
    ) -> None:
        schema = self._schema(config, **fields)
        pending_before = schema.repartition_pending

        output = self._run([schema], execute=True, **run_options)

        assert reason in output
        schema.refresh_from_db()
        assert schema.repartition_pending == pending_before

    def test_refuses_a_schema_with_no_table_on_disk(self) -> None:
        schema = self._schema()

        with patch(f"{_COMMAND_MODULE}.build_delta_table_uri", return_value=f"{self.table_uri}-missing"):
            output = self._run([schema], execute=True)

        assert "no_delta_table" in output
        schema.refresh_from_db()
        assert schema.repartition_pending is None

    def test_a_table_that_cannot_be_read_does_not_stop_the_batch(self) -> None:
        # One bucket error would otherwise end the run with a traceback and no report for the rest.
        unreadable = self._schema()
        readable = self._schema()

        with patch(f"{_COMMAND_MODULE}.delta_storage_options", side_effect=[OSError("access denied"), {}]):
            output = self._run([unreadable, readable], execute=True)

        assert "read_failed" in output
        unreadable.refresh_from_db()
        readable.refresh_from_db()
        assert unreadable.repartition_pending is None
        assert readable.repartition_pending is not None
