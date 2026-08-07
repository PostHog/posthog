"""Nominate over-fragmented warehouse tables for the coarsening rewrite.

The automatic coarsening path only acts on tables that are clearly over-fragmented *and* clearly safe
to merge, and one of its conditions is no OOM history. That condition reads the same unreliable signal
that over-split most of these tables in the first place, so the backlog of already-damaged tables can
sit blocked indefinitely. This command is the operator's way in: it nominates tables, and the pipeline
still decides whether any coarser layout is actually safe.

What it does NOT do is rewrite anything. It sets a `coarsen_requested` marker on the schema; the next
sync's pre-extraction activity measures the live layout, picks a target that fits the memory budget (or
declines), and performs the rewrite under the pipeline lock with the existing crash-safe swap. A
nomination can therefore only ever be a no-op, never a rewrite into partitions too big to merge.

Rewrites are not free. Observed durations run from seconds for small tables to hours for the largest,
and the rewrite blocks that table's sync while it runs, so stage in small batches and prefer off-peak
for big tables. `--limit` caps the blast radius per invocation and defaults low on purpose.

Dry run by default; pass --execute to write the markers.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet
from django.utils import timezone

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
    min_splittable_partition_bytes,
)

# Datetime tiers fine enough to be worth reviewing. Coarser layouts are not over-fragmented by tier.
FINE_DATETIME_FORMATS = ("hour", "day", "week")


class Command(BaseCommand):
    help = "Nominate over-fragmented external data schemas for the coarsening rewrite (dry run by default)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--execute", action="store_true", help="Write the markers (default is a dry run).")
        parser.add_argument(
            "--limit",
            type=int,
            default=25,
            help="Maximum schemas to nominate. Kept low because each rewrite blocks that table's sync.",
        )
        parser.add_argument(
            "--max-partition-bytes",
            type=int,
            default=None,
            help=(
                "Only consider schemas whose recorded largest partition is below this. "
                "Defaults to min_splittable_partition_bytes(), the same threshold the automatic path "
                "treats as over-fragmented, so the two cannot drift apart."
            ),
        )
        parser.add_argument("--team-id", type=int, default=None, help="Restrict to one team.")
        parser.add_argument("--source-type", type=str, default=None, help="Restrict to one source type.")
        parser.add_argument(
            "--schema-id",
            type=str,
            action="append",
            default=None,
            help="Nominate specific schemas by id. Repeatable, and skips the shape filters below.",
        )
        parser.add_argument(
            "--requested-by",
            type=str,
            default="stage_warehouse_coarsening",
            help="Recorded on the marker so a nomination can be traced back to whoever staged it.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be at least 1")
        threshold = options["max_partition_bytes"] or min_splittable_partition_bytes()

        candidates = list(self._candidates(options, threshold)[:limit])
        if not candidates:
            self.stdout.write("No candidates matched.")
            return

        self._report(candidates, threshold)

        if not options["execute"]:
            self.stdout.write(self.style.WARNING(f"\nDry run. Re-run with --execute to nominate {len(candidates)}."))
            return

        for schema in candidates:
            schema.set_coarsen_requested(
                {"requested_at": timezone.now().isoformat(), "requested_by": options["requested_by"]}
            )
        self.stdout.write(self.style.SUCCESS(f"\nNominated {len(candidates)}. Each is evaluated on its next sync."))

    def _candidates(self, options: dict[str, Any], threshold: int) -> QuerySet[ExternalDataSchema]:
        queryset = ExternalDataSchema.objects.filter(deleted=False, should_sync=True).exclude(
            sync_type=ExternalDataSchema.SyncType.CDC
        )
        if options["team_id"]:
            queryset = queryset.filter(team_id=options["team_id"])
        if options["source_type"]:
            queryset = queryset.filter(source__source_type=options["source_type"])

        if options["schema_id"]:
            # Explicit ids are the operator naming tables directly, so the shape filters don't apply.
            # The pipeline still refuses anything it can't coarsen safely.
            return queryset.filter(id__in=options["schema_id"])

        # Anything already queued for a rewrite, mid-swap, or waiting on a corruption revive is left
        # alone: nominating it would either be ignored or fight work that is already under way.
        queryset = queryset.filter(
            sync_type_config__max_partition_bytes__lt=threshold,
            sync_type_config__partition_format__in=FINE_DATETIME_FORMATS,
        ).exclude(sync_type_config__has_any_keys=["repartition_pending", "repartition_swap", "delta_revive_required"])
        # Worst first: the smaller the largest partition, the more the table was over-split.
        return queryset.select_related("source").order_by("sync_type_config__max_partition_bytes")

    def _report(self, candidates: list[ExternalDataSchema], threshold: int) -> None:
        self.stdout.write(f"Largest-partition threshold: {threshold:,} bytes\n")
        self.stdout.write(f"{'schema_id':38} {'team':>7} {'source':14} {'format':6} {'largest_bytes':>14}  name")
        for schema in candidates:
            self.stdout.write(
                f"{str(schema.id):38} {schema.team_id:>7} {schema.source.source_type:14} "
                f"{str(schema.partition_format or '-'):6} {schema.max_partition_bytes or 0:>14,}  {schema.name}"
            )
