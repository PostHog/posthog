from datetime import datetime
from time import sleep
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

import structlog

from posthog.schema import InsightVizNode

from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query

from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Backfill `query` from legacy `filters` on insights that still lack one — the same conversion "
        "as migration 0545, for rows created since it ran. Empty shells (no query, no filters) convert "
        "to the default empty trends query they already render as. Dry-run by default; pass --live to "
        "write. Rows locked by concurrent writers are skipped, so re-run to pick up any remainder."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--live", action="store_true", help="Write changes (default is a read-only report)")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--sleep-interval", type=float, default=0.1, help="Seconds to sleep between batches")
        parser.add_argument("--team-id", type=int, help="Only process insights of this team")

    def handle(self, *args: Any, **options: Any) -> None:
        live: bool = options["live"]
        batch_size: int = options["batch_size"]
        sleep_interval: float = options["sleep_interval"]
        team_id: int | None = options["team_id"]

        # Soft-deleted insights are included: they can be restored from the trash, so they need a query too.
        # Empty shells (no query, no filters) are included too: filter_to_query({}) yields the same empty
        # trends query they already render as at read time, so converting them changes nothing visible.
        base = Insight.objects_including_soft_deleted.filter(query__isnull=True)
        shells = Insight.objects_including_soft_deleted.filter(query__isnull=True, filters={})
        if team_id is not None:
            base = base.filter(team_id=team_id)
            shells = shells.filter(team_id=team_id)

        total = base.count()
        self.stdout.write(f"{total} insights without a query")
        self.stdout.write(f"of which {shells.count()} empty shells (no filters either) — get the default trends query")
        if not live:
            self.stdout.write(self.style.WARNING("Dry run — pass --live to write"))

        # Same stamp convention as migration 0545: lets us find rows converted by this run to roll back.
        migrated_at = str(datetime.now())
        converted = 0
        errors: dict[str, list[int]] = {}
        metadata_errors: dict[str, list[int]] = {}
        cursor = 0

        while True:
            with transaction.atomic():
                batch_qs = (
                    base.filter(id__gt=cursor)
                    .order_by("id")
                    .select_related("team")
                    .only("id", "filters", "query", "query_metadata", "team")
                )
                if live:
                    batch_qs = batch_qs.select_for_update(skip_locked=True, of=("self",))
                batch = list(batch_qs[:batch_size])
                if not batch:
                    break

                to_update = []
                for insight in batch:
                    try:
                        query = InsightVizNode(source=filter_to_query(insight.filters)).model_dump(exclude_none=True)
                    except Exception as e:
                        errors.setdefault(type(e).__name__, []).append(insight.id)
                        continue
                    insight.query = query
                    try:
                        # bulk_update skips the save() hook that derives this, so derive it here — without it
                        # a converted insight drops out of the `events` list filter and Max's insight search.
                        insight.generate_query_metadata()
                    except Exception as e:
                        # Best effort: the row still converts, and backfill_insights_query_metadata
                        # sweeps rows whose metadata stayed null.
                        logger.warning("query_metadata generation failed", insight_id=insight.id, error=str(e))
                        metadata_errors.setdefault(type(e).__name__, []).append(insight.id)
                    insight.filters["migrated_at"] = migrated_at
                    to_update.append(insight)

                if live and to_update:
                    # bulk_update bypasses save() and auto_now, so updated_at/last_modified_at stay put and
                    # "recently modified" orderings don't get churned by a background backfill.
                    Insight.objects_including_soft_deleted.bulk_update(
                        to_update, ["query", "filters", "query_metadata"]
                    )
                converted += len(to_update)
                cursor = batch[-1].id

            self.stdout.write(f"...{converted}/{total} converted, cursor at insight id {cursor}")
            if sleep_interval > 0:
                sleep(sleep_interval)

        failed = sum(len(ids) for ids in errors.values())
        verb = "Converted" if live else "Would convert"
        style = self.style.SUCCESS if failed == 0 else self.style.WARNING
        self.stdout.write(style(f"{verb} {converted} of {total} insights ({failed} failed)"))
        for error_type, ids in sorted(errors.items(), key=lambda kv: -len(kv[1])):
            self.stdout.write(f"  {error_type}: {len(ids)} insights, e.g. {ids[:5]}")

        metadata_failed = sum(len(ids) for ids in metadata_errors.values())
        if metadata_failed:
            self.stdout.write(
                self.style.WARNING(
                    f"{metadata_failed} converted insights have no query_metadata — "
                    f"run backfill_insights_query_metadata to sweep them"
                )
            )
            for error_type, ids in sorted(metadata_errors.items(), key=lambda kv: -len(kv[1])):
                self.stdout.write(f"  {error_type}: {len(ids)} insights, e.g. {ids[:5]}")
