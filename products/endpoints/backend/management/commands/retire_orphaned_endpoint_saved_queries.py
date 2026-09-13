"""Retire endpoint saved queries that no endpoint version points at.

Such a query cannot materialize: rebuilding its HogQL needs a version, so every
scheduled run fails. The Temporal activity now drops the DAG node on the first
such failure, which stops the burn. This command clears what the node removal
deliberately leaves behind - the `is_materialized` flag and the backing table -
so the query stops reading as a healthy materialization.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

import structlog

from products.data_modeling.backend.facade.api import delete_node_from_dag
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Retire endpoint saved queries with no linked endpoint version"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, help="Only look at this team")
        parser.add_argument("--saved-query-id", type=str, help="Only act on this saved query")
        parser.add_argument("--apply", action="store_true", help="Write the changes (default is a dry run)")

    def handle(self, *args: Any, **options: Any) -> None:
        apply = options["apply"]
        queryset = (
            DataWarehouseSavedQuery.objects.filter(origin=DataWarehouseSavedQuery.Origin.ENDPOINT)
            .exclude(deleted=True)
            .filter(endpoint_versions__isnull=True)
            .select_related("table")
            .order_by("team_id", "created_at")
        )
        if options["team_id"]:
            queryset = queryset.filter(team_id=options["team_id"])
        if options["saved_query_id"]:
            queryset = queryset.filter(id=options["saved_query_id"])

        orphans = list(queryset)
        if not orphans:
            self.stdout.write("No orphaned endpoint saved queries found.")
            return

        self.stdout.write(f"Found {len(orphans)} orphaned endpoint saved queries:")
        for saved_query in orphans:
            self.stdout.write(
                f"  team {saved_query.team_id}  {saved_query.name}  "
                f"materialized={saved_query.is_materialized}  table={saved_query.table_id is not None}"
            )

        if not apply:
            self.stdout.write("\nDry run. Re-run with --apply to retire them.")
            return

        retired = 0
        for saved_query in orphans:
            try:
                delete_node_from_dag(saved_query)
                saved_query.revert_materialization()
                saved_query.soft_delete()
            except Exception:
                logger.exception(
                    "Failed to retire orphaned endpoint saved query",
                    saved_query_id=str(saved_query.id),
                    team_id=saved_query.team_id,
                )
                self.stderr.write(f"  FAILED team {saved_query.team_id} {saved_query.name}")
                continue
            retired += 1
            self.stdout.write(f"  retired team {saved_query.team_id} {saved_query.name}")

        self.stdout.write(f"\nRetired {retired} of {len(orphans)}.")
        if retired != len(orphans):
            raise CommandError("Some saved queries could not be retired - see the errors above.")
