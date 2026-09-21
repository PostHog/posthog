from argparse import ArgumentParser
from datetime import datetime
from typing import cast

from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.models import Team

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import RelatedTo
from products.signals.backend.billing import BILLING_EXEMPT_SOURCE_PRODUCTS
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.recurrence import fixed_dismissal_at, recurrence_report
from products.signals.backend.temporal.signal_queries import _ensure_tz_aware, fetch_signals_for_report_sync


def _signals_since(team: Team, report_id: str, since: datetime) -> list[dict]:
    """Return recurrence evidence in timestamp order."""
    return sorted(
        [
            signal
            for signal in fetch_signals_for_report_sync(team, report_id)
            if _ensure_tz_aware(signal["timestamp"]) > since
        ],
        key=lambda signal: _ensure_tz_aware(signal["timestamp"]),
    )


class Command(BaseCommand):
    help = (
        "Fork a fresh report for every report dismissed as fixed that has absorbed signals since. "
        "Before the grouping stage learned to fork on recurrence, such a report was a permanent "
        "sink, so the evidence that the fix did not hold is buried on it. One fork per parent, not "
        "one per signal, carrying the parent's title and summary. Historical signals stay on the "
        "parent and do not count toward the fork's promotion. The fork lands in `potential` under "
        "the normal thresholds rather than spawning research from this command. Safe to rerun: a "
        "parent that already has a successor is skipped."
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
            if recurrence_report(report) is not None:
                skipped += 1
                continue
            if report.team_id not in teams:
                teams[report.team_id] = Team.objects.get(pk=report.team_id)
            signals = _signals_since(teams[report.team_id], str(report.id), dismissed_at)
            count = len(signals)
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
                report = SignalReport.objects.select_for_update().get(id=report.id, team_id=report.team_id)
                if (
                    report.status != SignalReport.Status.SUPPRESSED
                    or fixed_dismissal_at(report) != dismissed_at
                    or recurrence_report(report, lock=True) is not None
                ):
                    skipped += 1
                    continue
                fork = SignalReport.objects.create(
                    team_id=report.team_id,
                    status=SignalReport.Status.POTENTIAL,
                    title=report.title,
                    summary=report.summary,
                    recurrence_parent=report,
                    billing_exempt_reason=BILLING_EXEMPT_SOURCE_PRODUCTS.get(signals[0]["source_product"]),
                )
                SignalReportArtefact.add_log(
                    team_id=report.team_id,
                    report_id=str(fork.id),
                    content=RelatedTo(report_id=str(report.id)),
                    attribution=ArtefactAttribution.system(),
                )
            forked += 1
            self.stdout.write(f"Forked {fork.id} from {report.id} ({count} absorbed signals)")

        self.stdout.write(f"Done. Forked {forked}, skipped {skipped} parents with a successor or changed state.")
