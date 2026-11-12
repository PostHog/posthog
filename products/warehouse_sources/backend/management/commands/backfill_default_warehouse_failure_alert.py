"""Give projects that already have warehouse sources their default sync failure email alert.

New projects get the alert when they add their first source. This command covers projects that
added sources earlier. It applies the same rules: only with the feature flag on for the project,
never for a project that has its own warehouse source alert, and never again after a person
deleted the default.
"""

from collections import Counter
from itertools import batched
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from posthog.models import Team

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.sync_alerts.default_alert import (
    DefaultAlertOutcome,
    ensure_default_failure_alert,
)

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 100
FAILED = "failed"


class Command(BaseCommand):
    help = (
        "Create the default warehouse sync failure email alert for projects with at least one warehouse source. "
        "Pass --dry-run to report what it would do without writing anything."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--team-ids",
            type=int,
            nargs="+",
            default=None,
            help="Only process these projects. Each still needs a warehouse source.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help="How many projects to load at a time.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report what would happen. Write nothing.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids: list[int] | None = options["team_ids"]
        batch_size: int = options["batch_size"]
        dry_run: bool = options["dry_run"]
        if batch_size < 1:
            raise CommandError("--batch-size must be 1 or greater")

        candidates = (
            # `deleted` is nullable, and a NULL row is not deleted.
            ExternalDataSource.objects.exclude(deleted=True)
            .order_by("team_id")
            .values_list("team_id", flat=True)
            .distinct()
        )
        if team_ids is not None:
            candidates = candidates.filter(team_id__in=team_ids)

        counts: Counter[str] = Counter()
        for batch in batched(candidates.iterator(chunk_size=batch_size), batch_size, strict=False):
            for team in Team.objects.filter(id__in=batch).order_by("id"):
                try:
                    outcome = ensure_default_failure_alert(team, dry_run=dry_run)
                except Exception as error:
                    counts[FAILED] += 1
                    logger.exception("Could not create the default warehouse failure alert", team_id=team.id)
                    self.stderr.write(f"team {team.id}: {type(error).__name__}")
                    continue
                counts[outcome.value] += 1
            logger.info("Default warehouse failure alert backfill progress", dry_run=dry_run, **counts)

        created_label = "would create" if dry_run else "created"
        self.stdout.write(
            f"{created_label}: {counts[DefaultAlertOutcome.CREATED.value]}, "
            f"own alert: {counts[DefaultAlertOutcome.HAS_OWN_ALERT.value]}, "
            f"already decided: {counts[DefaultAlertOutcome.ALREADY_DECIDED.value]}, "
            f"flag off: {counts[DefaultAlertOutcome.FLAG_OFF.value]}, "
            f"failed: {counts[FAILED]}"
        )
        if dry_run:
            self.stdout.write("Dry run, nothing written.")
        if counts[FAILED]:
            raise CommandError(f"{counts[FAILED]} project(s) failed. See the errors above, then run the command again.")
