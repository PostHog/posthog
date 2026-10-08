"""Stage in-place rewrites of datetime-partitioned warehouse tables into a coarser tier.

This is for tables that were split finer than their data needs. The automatic coarsening path only
merges a table when every resulting partition fits half the repartition budget, which keeps the
controller from splitting and merging the same table in turns. A table that was split from just over
the budget can never meet that, so `stage_warehouse_coarsening` refuses it. Here the operator names
the tier, and the only limit is the budget itself.

What it does NOT do is rewrite anything. It stages the same `repartition_pending` target as the admin
page, and each table's next scheduled sync runs the rewrite before it extracts. The rewrite holds that
sync until it finishes, which takes hours for the largest tables, so stage big tables off-peak. A
scheduled full refresh skips the repartition step, so the target then waits for the sync after it.

Unlike the admin page, it measures the live table first and refuses a target whose largest partition
would be over the budget. A partition over the budget is what makes a merge run out of memory, and the
rewrite has no size check of its own for an operator's target.

Dry run by default; pass --execute to stage.
"""

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

import deltalake

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (
    build_delta_table_uri,
    delta_storage_options,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    DATETIME_FORMAT_TIERS,
    measure_partition_bytes,
    simulate_datetime_coarsening,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
    target_partition_bytes,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionFormat


class Command(BaseCommand):
    help = "Stage in-place rewrites of datetime-partitioned schemas into a coarser tier (dry run by default)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--execute", action="store_true", help="Stage the rewrites (default is a dry run).")
        parser.add_argument(
            "--schema-id", type=UUID, action="append", default=None, help="Schema to rewrite. Repeatable."
        )
        parser.add_argument(
            "--format",
            choices=DATETIME_FORMAT_TIERS,
            required=True,
            help="Tier to rewrite every named schema into. It must be coarser than the schema's current tier.",
        )

    def _measure(self, schema: ExternalDataSchema) -> dict[str | None, int] | None:
        uri = build_delta_table_uri(schema.folder_path(), schema.resolved_s3_folder_name or schema.name)
        storage_options = delta_storage_options()
        if not deltalake.DeltaTable.is_deltatable(uri, storage_options=storage_options):
            return None
        return measure_partition_bytes(deltalake.DeltaTable(uri, storage_options=storage_options))

    def _refusal_before_measuring(self, schema: ExternalDataSchema, target_format: PartitionFormat) -> str | None:
        if not schema.should_sync:
            return "not_syncing: no sync will run the rewrite"
        if schema.sync_type == ExternalDataSchema.SyncType.CDC:
            return "cdc: repartitioning excludes CDC schemas"
        if (
            schema.repartition_pending is not None
            or schema.repartition_swap is not None
            or schema.delta_revive_required is not None
        ):
            return "busy: a rewrite or a corruption revive is already queued"
        if schema.partition_mode != "datetime":
            return f"not_datetime: partition mode is {schema.partition_mode}"
        current_format = schema.partition_format or "month"
        if DATETIME_FORMAT_TIERS.index(target_format) >= DATETIME_FORMAT_TIERS.index(current_format):
            return f"not_coarser: the table is at {current_format}"
        if not schema.partitioning_keys:
            return "no_partition_key: the schema records no partitioning key to rebuild from"
        return None

    def _plan(
        self, schema: ExternalDataSchema, target_format: PartitionFormat, budget: int
    ) -> tuple[str, dict[str, Any] | None]:
        """The report text for one schema, and the target to stage when the rewrite is safe."""
        refusal = self._refusal_before_measuring(schema, target_format)
        if refusal is not None:
            return f"REFUSED {refusal}", None

        try:
            partition_bytes = self._measure(schema)
        except Exception as e:
            # A bucket or credential error on one table must not end the batch with no report for the rest.
            return f"REFUSED read_failed: {type(e).__name__}: {e}", None
        if not partition_bytes:
            return "REFUSED no_delta_table: nothing on disk to rewrite", None
        simulated = simulate_datetime_coarsening(partition_bytes, schema.partition_format or "month", target_format)
        if simulated is None:
            return "REFUSED unparseable_partition_keys: a partition key is not a date in the current tier", None

        layout = (
            f"{len(partition_bytes):,} -> {len(simulated):,} partitions, "
            f"largest {max(partition_bytes.values()):,} -> {max(simulated.values()):,} bytes"
        )
        if max(simulated.values()) > budget:
            return f"REFUSED over_budget: {layout}", None
        return f"OK {layout}", {
            "partition_mode": "datetime",
            "partition_format": target_format,
            "partition_count": None,
            "partition_size": None,
            "partition_keys": schema.partitioning_keys,
            "trigger_reason": "admin",
            "attempts": 0,
        }

    def handle(self, *args: Any, **options: Any) -> None:
        schema_ids = [str(schema_id) for schema_id in options["schema_id"] or []]
        if not schema_ids:
            raise CommandError("Name at least one schema with --schema-id")
        target_format: PartitionFormat = options["format"]
        budget = target_partition_bytes()

        schemas = {
            str(schema.id): schema
            for schema in ExternalDataSchema.objects.filter(id__in=schema_ids, deleted=False).select_related("source")
        }
        self.stdout.write(f"Target tier: {target_format}. Budget per partition: {budget:,} bytes\n")
        # Every table is planned before anything is written, so a crash part way through stages nothing.
        targets: dict[str, dict[str, Any]] = {}
        for schema_id in schema_ids:
            schema = schemas.get(schema_id)
            if schema is None:
                self.stdout.write(f"{schema_id}  REFUSED not_found: no such schema")
                continue
            verdict, target = self._plan(schema, target_format, budget)
            self.stdout.write(f"{schema_id}  team={schema.team_id} {schema.name}  {verdict}")
            if target is not None:
                targets[schema_id] = target

        if not options["execute"]:
            self.stdout.write(self.style.WARNING(f"\nDry run. Re-run with --execute to stage {len(targets)}."))
            return

        for schema_id, target in targets.items():
            schemas[schema_id].set_repartition_pending(target)
        self.stdout.write(
            self.style.SUCCESS(
                f"\nStaged {len(targets)}. Each rewrites on its next sync that is not a full refresh, and holds that sync until done."
            )
        )
