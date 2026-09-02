from datetime import datetime
from time import sleep
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

import structlog

from posthog.schema import InsightVizNode, QuerySchemaRoot

from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query

from products.product_analytics.backend.legacy_filter_repair import (
    SQL_INSIGHT_TYPES,
    normalized_insight_type,
    repair_filters,
)
from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

REPAIRS_KEY = "migration_repairs"


def sql_query_from_filters(filters: dict[str, Any]) -> dict[str, Any] | None:
    """Build the query for a SQL insight, which keeps its SQL in `filters` instead of a query node."""
    raw = filters.get("query")
    if isinstance(raw, dict):
        if raw.get("kind"):
            return raw
        raw = raw.get("query")
    if isinstance(raw, str) and raw.strip():
        return {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": raw}}
    return None


def validated(query: dict[str, Any]) -> dict[str, Any]:
    """Reject anything /query would reject, so a stored query is always one that can run."""
    QuerySchemaRoot.model_validate(query)
    return query


def _convert(filters: dict[str, Any]) -> dict[str, Any]:
    return InsightVizNode(source=filter_to_query(filters)).model_dump(exclude_none=True)


def query_from_filters(filters: Any) -> tuple[dict[str, Any], list[str]]:
    """Convert legacy filters, repairing them only when they cannot convert as they stand.

    Returns the query and the name of every repair applied. Raises when even repaired filters fail.
    """
    filters = filters if isinstance(filters, dict) else {}

    if normalized_insight_type(filters) in SQL_INSIGHT_TYPES:
        sql_query = sql_query_from_filters(filters)
        if sql_query is None:
            raise ValueError("SQL insight without a usable query")
        return validated(sql_query), ["insight:sql"]

    try:
        return validated(_convert(filters)), []
    except Exception:
        repaired, repairs = repair_filters(filters)
        # A second failure propagates, and the caller reports it against the original row.
        return validated(_convert(repaired)), repairs


class Command(BaseCommand):
    help = (
        "Backfill `query` from legacy `filters` on insights that still lack one — the same conversion "
        "as migration 0545, for rows created since it ran. Filters that cannot convert are repaired "
        "first: `filters` was never validated, so it holds values the schema does not accept, which "
        "means those insights fail at query time today. A repair maps a value when it has one clear "
        "reading and drops it to the schema default when it does not. Empty shells (no query, no "
        "filters) convert to the default empty trends query they already render as. Dry-run by "
        "default; pass --live to write. Rows locked by concurrent writers are skipped, so re-run to "
        "pick up any remainder."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--live", action="store_true", help="Write changes (default is a read-only report)")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--sleep-interval", type=float, default=0.1, help="Seconds to sleep between batches")
        parser.add_argument("--team-id", type=int, help="Only process insights of this team")
        parser.add_argument(
            "--no-repair",
            action="store_true",
            help="Convert only filters that already convert, and report the rest as failures",
        )
        parser.add_argument(
            "--rollback",
            metavar="STAMP",
            help=(
                "Undo one run: clear `query` on the insights it stamped with this exact `migrated_at`. "
                "List the stamps with --list-stamps. Scoped to a single run on purpose, because "
                "clearing every stamped row would also undo migration 0545."
            ),
        )
        parser.add_argument(
            "--list-stamps", action="store_true", help="Show each `migrated_at` stamp and how many rows carry it"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int | None = options["team_id"]

        if options["list_stamps"]:
            self._list_stamps(team_id)
            return
        if options["rollback"]:
            self._rollback(options["rollback"], team_id, options["live"])
            return

        self._backfill(
            live=options["live"],
            batch_size=options["batch_size"],
            sleep_interval=options["sleep_interval"],
            team_id=team_id,
            repair=not options["no_repair"],
        )

    def _stamped(self, team_id: int | None):
        qs = Insight.objects_including_soft_deleted.filter(filters__has_key="migrated_at")
        return qs.filter(team_id=team_id) if team_id is not None else qs

    def _list_stamps(self, team_id: int | None) -> None:
        counts: dict[str, int] = {}
        for filters in self._stamped(team_id).values_list("filters", flat=True).iterator(chunk_size=500):
            stamp = (filters or {}).get("migrated_at")
            if stamp:
                counts[str(stamp)] = counts.get(str(stamp), 0) + 1
        if not counts:
            self.stdout.write("No stamped insights")
            return
        self.stdout.write(f"{len(counts)} stamps:")
        for stamp, count in sorted(counts.items()):
            self.stdout.write(f"  {count:>6}  {stamp}")

    def _rollback(self, stamp: str, team_id: int | None, live: bool) -> None:
        batch = list(self._stamped(team_id).filter(filters__migrated_at=stamp).only("id", "filters", "query"))
        self.stdout.write(f"{len(batch)} insights stamped {stamp!r}")
        if not live:
            self.stdout.write(self.style.WARNING("Dry run — pass --live to write"))
            return
        for insight in batch:
            insight.query = None
            insight.query_metadata = None
            insight.filters.pop("migrated_at", None)
            insight.filters.pop(REPAIRS_KEY, None)
        Insight.objects_including_soft_deleted.bulk_update(batch, ["query", "filters", "query_metadata"])
        self.stdout.write(self.style.SUCCESS(f"Reverted {len(batch)} insights"))

    def _backfill(
        self, *, live: bool, batch_size: int, sleep_interval: float, team_id: int | None, repair: bool
    ) -> None:
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

        # Same stamp convention as migration 0545, and unique per run so --rollback can target this one.
        migrated_at = str(datetime.now())
        converted = 0
        repaired_count = 0
        repair_counts: dict[str, int] = {}
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
                        if repair:
                            query, repairs = query_from_filters(insight.filters)
                        else:
                            query, repairs = validated(_convert(insight.filters or {})), []
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
                    if not isinstance(insight.filters, dict):
                        insight.filters = {}
                    insight.filters["migrated_at"] = migrated_at
                    if repairs:
                        repaired_count += 1
                        # Recorded on the row so a repaired insight stays findable for review.
                        insight.filters[REPAIRS_KEY] = repairs
                        for name in repairs:
                            repair_counts[name] = repair_counts.get(name, 0) + 1
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
        if live and converted:
            self.stdout.write(f"Stamp for this run (pass to --rollback to undo it): {migrated_at!r}")
        for error_type, ids in sorted(errors.items(), key=lambda kv: -len(kv[1])):
            self.stdout.write(f"  {error_type}: {len(ids)} insights, e.g. {ids[:5]}")

        if repaired_count:
            self.stdout.write(
                f"{repaired_count} insights needed a repair first — their filters held values the schema "
                f"does not accept, so they could not run before either:"
            )
            for name, count in sorted(repair_counts.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f"  {count:>5}  {name}")

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
