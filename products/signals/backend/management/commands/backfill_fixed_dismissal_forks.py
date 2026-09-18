from argparse import ArgumentParser
from datetime import datetime
from typing import cast

from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import RelatedTo
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.recurrence import fixed_dismissal_at, open_recurrence_report
from products.signals.backend.temporal.signal_queries import fetch_signals_for_report_sync


def _signals_since(team: Team, report_id: str, since: datetime) -> tuple[int, float]:
    """Count the report's signals that arrived after `since`, and sum their weights."""
    count = 0
    weight = 0.0
    for signal in fetch_signals_for_report_sync(team, report_id):
        timestamp = signal["timestamp"]
        if isinstance(timestamp, datetime) and timestamp > since:
            count += 1
            weight += float(signal["weight"] or 0.0)
    return count, weight


class Command(BaseCommand):
    help = (
        "Fork a fresh report for every report dismissed as fixed that has absorbed signals since. "
        "Before the grouping stage learned to fork on recurrence, such a report was a permanent "
        "sink, so the evidence that the fix did not hold is buried on it. One fork per parent, not "
        "one per signal, carrying the parent's title, summary and the weight of the absorbed "
        "signals. The fork lands in `potential`, so it promotes on the next matching signal under "
        "the normal thresholds rather than spawning research from this command. Safe to rerun: a "
        "parent that already has an open fork is skipped."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only fork reports for this team.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be forked without writing anything.",
        )

    def handle(self, *args: object, **options: object) -> None:
        team_id = cast(int | None, options["team_id"])
        dry_run = cast(bool, options["dry_run"])

        reports = SignalReport.objects.filter(status=SignalReport.Status.SUPPRESSED).order_by("created_at")
        if team_id is not None:
            reports = reports.filter(team_id=team_id)

        teams: dict[int, Team] = {}
        forked = 0
        skipped = 0
        for report in reports.iterator():
            dismissed_at = fixed_dismissal_at(report)
            if dismissed_at is None:
                continue
            if open_recurrence_report(report, after=dismissed_at) is not None:
                skipped += 1
                continue
            team = teams.setdefault(report.team_id, Team.objects.get(pk=report.team_id))
            count, weight = _signals_since(team, str(report.id), dismissed_at)
            if count == 0:
                continue

            if dry_run:
                self.stdout.write(
                    f"[dry-run] would fork report {report.id} (team {report.team_id}): "
                    f"{count} signals absorbed since {dismissed_at.isoformat()}"
                )
                forked += 1
                continue

            with transaction.atomic():
                fork = SignalReport.objects.create(
                    team_id=report.team_id,
                    status=SignalReport.Status.POTENTIAL,
                    total_weight=weight,
                    signal_count=count,
                    title=report.title,
                    summary=report.summary,
                    # The fork inherits the parent's exemption: it is the same issue, and the
                    # signals it counts were billed (or exempted) on the parent already.
                    billing_exempt_reason=report.billing_exempt_reason,
                )
                SignalReportArtefact.add_log(
                    team_id=report.team_id,
                    report_id=str(fork.id),
                    content=RelatedTo(report_id=str(report.id)),
                    attribution=ArtefactAttribution.system(),
                )
            forked += 1
            self.stdout.write(f"Forked {fork.id} from {report.id} ({count} absorbed signals)")

        self.stdout.write(f"Done. Forked {forked}, skipped {skipped} parents that already have an open fork.")
