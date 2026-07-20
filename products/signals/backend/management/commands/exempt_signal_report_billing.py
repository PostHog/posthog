"""Ops escape hatch: mark a signal report never-billable (system billing exemption).

For ad-hoc cases the auto-start policy doesn't cover. Prospective-only, like every exemption
setter: refuses once the report has a billable PR run — anything already billable is handled as a
refund, never a late exemption (flipping the flag after billing may have observed the run would
break usage-report determinism).
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.billing import BillingExemptionError, mark_report_billing_exempt
from products.signals.backend.models import SignalReport


class Command(BaseCommand):
    help = "Mark a signal report never-billable. Refuses if a billable PR run already exists (use a refund)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("team_id", type=int, help="Team the report belongs to")
        parser.add_argument("report_id", type=str, help="SignalReport id (UUID)")
        parser.add_argument(
            "reason",
            type=str,
            choices=list(SignalReport.BillingExemptReason.values),
            help="Exemption reason (posthog_system is the generic ops value)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = SignalReport.objects.filter(team_id=options["team_id"], id=options["report_id"]).first()
        if report is None:
            raise CommandError(f"Report {options['report_id']} not found for team {options['team_id']}")

        try:
            changed = mark_report_billing_exempt(report, options["reason"])
        except BillingExemptionError as e:
            raise CommandError(str(e))

        if not changed:
            self.stdout.write(
                self.style.WARNING(
                    f"Report {report.id} is already billing-exempt ({report.billing_exempt_reason}); left unchanged."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(f"Report {report.id} marked billing-exempt ({report.billing_exempt_reason}).")
        )
