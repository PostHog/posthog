"""Backfill `SignalReport.source_products` from ClickHouse signal provenance.

New reports populate `source_products` at creation/summary, but rows that predate the column
have an empty array. Run this once per team before enabling the `signals-scout-inbox` flag, so
the inbox visibility gate (which filters on the column) has accurate provenance for old reports.

Idempotent: re-running recomputes the set from ClickHouse and only writes when it differs.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from posthog.models.team.team import Team

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.signal_queries import fetch_source_products_for_reports

BATCH_SIZE = 200


class Command(BaseCommand):
    help = "Backfill SignalReport.source_products from ClickHouse signal provenance."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, help="Backfill a single team. Omit to backfill all teams.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")

    def handle(self, *args, **options):
        team_id = options.get("team_id")
        dry_run = options.get("dry_run", False)

        team_ids = (
            [team_id] if team_id else list(SignalReport.objects.order_by().values_list("team_id", flat=True).distinct())
        )
        if team_id and not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team {team_id} does not exist.")

        total_updated = 0
        for tid in team_ids:
            team = Team.objects.get(id=tid)
            total_updated += self._backfill_team(team, dry_run)
        self.stdout.write(
            self.style.SUCCESS(f"Done. {total_updated} report(s) {'would be ' if dry_run else ''}updated.")
        )

    def _backfill_team(self, team: Team, dry_run: bool) -> int:
        reports = list(SignalReport.objects.filter(team=team).values_list("id", flat=True))
        updated = 0
        for start in range(0, len(reports), BATCH_SIZE):
            batch = [str(rid) for rid in reports[start : start + BATCH_SIZE]]
            source_map = fetch_source_products_for_reports(team, batch)
            for report in SignalReport.objects.filter(team=team, id__in=batch):
                desired = source_map.get(str(report.id), [])
                if report.source_products == desired:
                    continue
                updated += 1
                if not dry_run:
                    report.source_products = desired
                    report.save(update_fields=["source_products"])
        self.stdout.write(f"team {team.id}: {updated} report(s) {'would change' if dry_run else 'updated'}")
        return updated
