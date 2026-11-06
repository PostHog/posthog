"""Add explicit warehouse links to sources created before destination links existed.

New sources now receive a link during setup. This command covers older sources so their
destination set no longer depends on the implicit fallback during normal operation.
"""

from itertools import groupby, islice
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

import structlog

from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    ExternalDataSourceDestination,
    get_or_create_warehouse_destination,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


class Command(BaseCommand):
    help = (
        "Link sources without destinations to their team's PostHog warehouse. "
        "Previews by default; pass --live-run to persist."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only process sources belonging to this team.")
        parser.add_argument("--limit", type=int, default=None, help="Only scan the first N sources.")
        parser.add_argument(
            "--live-run", action="store_true", help="Create links. Without this the command only reports what it found."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int | None = options["team_id"]
        limit: int | None = options["limit"]
        live_run: bool = options["live_run"]
        if limit is not None and limit < 0:
            raise CommandError("--limit must be zero or greater")

        # Ordered by team so `groupby` below sees each team's sources together, and deleted
        # sources are left out: one never syncs again, so a link for it is noise.
        # `select_related(None)` clears the default manager's join, which `only()` cannot defer
        # past — without it Django refuses the query.
        sources = (
            ExternalDataSource.objects.exclude(deleted=True)
            .select_related(None)
            .only("id", "team_id")
            .order_by("team_id", "id")
        )
        if team_id is not None:
            sources = sources.filter(team_id=team_id)
        if limit is not None:
            sources = sources[:limit]

        scanned = 0
        skipped = 0
        links = 0
        failures = 0
        teams: set[int] = set()
        destination_teams: set[int] = set()
        source_iterator = sources.iterator(chunk_size=BATCH_SIZE)

        while batch := list(islice(source_iterator, BATCH_SIZE)):
            scanned += len(batch)
            for current_team_id, team_sources in groupby(batch, key=lambda source: source.team_id):
                grouped_sources = list(team_sources)
                scoped_links = ExternalDataSourceDestination.objects.for_team(current_team_id)
                missing = grouped_sources
                try:
                    linked_ids = set(
                        scoped_links.filter(source_id__in=[source.pk for source in grouped_sources]).values_list(
                            "source_id", flat=True
                        )
                    )
                    missing = [source for source in grouped_sources if source.pk not in linked_ids]
                    skipped += len(grouped_sources) - len(missing)
                    if not missing:
                        continue

                    teams.add(current_team_id)
                    destination_exists = (
                        ExternalDataDestination.objects.for_team(current_team_id)
                        .filter(type=ExternalDataDestination.Type.POSTHOG_WAREHOUSE, deleted=False)
                        .exists()
                    )
                    if not live_run:
                        links += len(missing)
                        if not destination_exists:
                            destination_teams.add(current_team_id)
                        continue

                    destination = get_or_create_warehouse_destination(current_team_id)
                    created = 0
                    failed = 0
                    skipped_during_run = 0
                    for source in missing:
                        # One savepoint per source, so a source that cannot be linked costs only
                        # itself. A transaction around the whole group would hold its locks for
                        # as long as the group takes.
                        try:
                            with transaction.atomic():
                                # Serialize with destination-set edits before checking for links.
                                ExternalDataSource.objects.select_for_update(of=("self",)).get(pk=source.pk)
                                if scoped_links.filter(source_id=source.pk).exists():
                                    skipped_during_run += 1
                                    continue
                                ExternalDataSourceDestination.objects.for_team(current_team_id).create(
                                    team_id=current_team_id,
                                    source=source,
                                    destination=destination,
                                    enabled=True,
                                )
                                created += 1
                        except Exception as error:
                            failed += 1
                            logger.exception(
                                "Could not link warehouse source",
                                source_id=str(source.pk),
                                team_id=current_team_id,
                                error=str(error),
                            )
                    links += created
                    failures += failed
                    skipped += skipped_during_run
                    if not destination_exists:
                        destination_teams.add(current_team_id)
                except Exception as error:
                    failures += len(missing)
                    logger.exception(
                        "Could not process warehouse source group",
                        team_id=current_team_id,
                        error=str(error),
                    )

            logger.info(
                "Warehouse source destination backfill progress",
                scanned=scanned,
                skipped=skipped,
                links=links,
                teams=len(teams),
                failures=failures,
            )

        link_label = "links created" if live_run else "links would create"
        destination_label = (
            "warehouse destination rows created" if live_run else "warehouse destination rows would create"
        )
        self.stdout.write(
            f"sources scanned: {scanned}, sources already linked (skipped): {skipped}, "
            f"{link_label}: {links}, teams touched: {len(teams)}, {destination_label}: {len(destination_teams)}, "
            f"failures: {failures}"
        )
        if not live_run:
            self.stdout.write("preview only, nothing written. Re-run with --live-run to persist.")
        if failures:
            raise CommandError(f"{failures} source(s) could not be linked; see the errors above and re-run")
