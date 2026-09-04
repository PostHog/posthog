from copy import deepcopy
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q

from products.product_analytics.backend.lineage.extraction import query_fingerprint, query_may_reference_data_models
from products.product_analytics.backend.lineage.synchronization import synchronize_insight_data_model_dependencies
from products.product_analytics.backend.models.insight import Insight


class Command(BaseCommand):
    help = "Backfill stable data model dependencies for saved insights. Runs as a dry run unless --apply is set."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--apply", action="store_true", help="Write dependency rows.")
        parser.add_argument("--team-id", type=int, help="Process one team only.")
        parser.add_argument("--batch-size", type=int, default=500, help="Rows to fetch per database batch.")
        parser.add_argument("--limit", type=int, help="Maximum number of insights to process.")
        parser.add_argument("--after-team-id", type=int, help="Resume after this team ID.")
        parser.add_argument("--after-insight-id", type=int, help="Resume after this insight ID within the team.")

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size = options["batch_size"]
        limit = options["limit"]
        if batch_size <= 0:
            raise CommandError("--batch-size must be greater than zero")
        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than zero")

        after_team_id = options["after_team_id"]
        after_insight_id = options["after_insight_id"]
        if (after_team_id is None) != (after_insight_id is None):
            raise CommandError("--after-team-id and --after-insight-id must be set together")

        insights = Insight.objects_including_soft_deleted.filter(
            deleted=False,
            saved=True,
            query__isnull=False,
        ).only("id", "team_id", "query")
        if options["team_id"] is not None:
            insights = insights.filter(team_id=options["team_id"])
        if after_team_id is not None and after_insight_id is not None:
            insights = insights.filter(Q(team_id__gt=after_team_id) | Q(team_id=after_team_id, id__gt=after_insight_id))
        insights = insights.order_by("team_id", "id")
        if limit is not None:
            insights = insights[:limit]

        processed = 0
        failed = 0
        skipped = 0
        stale = 0
        dependencies = 0
        last_cursor: tuple[int, int] | None = None
        for insight in insights.iterator(chunk_size=batch_size):
            last_cursor = (insight.team_id, insight.id)
            query_snapshot = deepcopy(insight.query)
            if not query_may_reference_data_models(query_snapshot):
                skipped += 1
                continue
            result = synchronize_insight_data_model_dependencies(
                team_id=insight.team_id,
                insight_id=insight.id,
                query_snapshot=query_snapshot,
                fingerprint=query_fingerprint(query_snapshot),
                insight_model=Insight,
                apply=options["apply"],
            )
            processed += 1
            dependencies += result.dependency_count
            if result.status == "failed":
                failed += 1
            elif result.status == "stale":
                stale += 1

        mode = "apply" if options["apply"] else "dry-run"
        cursor = f"{last_cursor[0]}:{last_cursor[1]}" if last_cursor is not None else "none"
        self.stdout.write(
            f"Mode: {mode}. Processed: {processed}. Skipped: {skipped}. "
            f"Dependencies: {dependencies}. Stale: {stale}. Failed: {failed}. Last cursor: {cursor}."
        )
        if failed:
            raise CommandError(f"Could not synchronize {failed} insights")
