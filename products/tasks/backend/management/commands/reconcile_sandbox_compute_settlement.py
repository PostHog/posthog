from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from products.tasks.backend.logic.services.compute_settlement import (
    TeamComputeDelta,
    reconcile_compute_settlement,
    unpark_sandbox_compute,
    wallet_team_id,
)
from products.tasks.backend.models import SandboxSession

CENT_ROUNDING_TOLERANCE_USD = Decimal("0.005")


class Command(BaseCommand):
    help = (
        "Report settled sandbox compute against the gateway ledger, per customer team. "
        "With --unpark, first return rows parked for that reason in the window to the settlement sweep"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--since", type=datetime.fromisoformat, default=None)
        parser.add_argument("--until", type=datetime.fromisoformat, default=None)
        parser.add_argument("--wallet-team-id", type=int, default=None)
        parser.add_argument(
            "--unpark",
            choices=[
                SandboxSession.ComputeSettleParkReason.ATTEMPTS_EXHAUSTED.value,
                SandboxSession.ComputeSettleParkReason.HTTP_400.value,
            ],
            default=None,
            help="Unpark rows parked for this reason within --since/--until so the sweep retries them",
        )

    def handle(self, *args: object, **options: object) -> None:
        until = options["until"] or timezone.now()
        if not isinstance(until, datetime):
            raise CommandError("--until must be an ISO-8601 timestamp")
        since = options["since"] or until - timedelta(days=7)
        if not isinstance(since, datetime):
            raise CommandError("--since must be an ISO-8601 timestamp")
        if timezone.is_naive(since) or timezone.is_naive(until) or until <= since:
            raise CommandError("--since and --until must be timezone-aware and --until must follow --since")
        unpark = options["unpark"]
        if isinstance(unpark, str):
            count = unpark_sandbox_compute(unpark, since, until)
            self.stdout.write(
                f"Unparked {count} sessions parked for {unpark} between {since.isoformat()} and {until.isoformat()}"
            )
        wallet = options["wallet_team_id"]
        wallet_team = wallet if isinstance(wallet, int) else wallet_team_id()

        report = reconcile_compute_settlement(since, until, wallet_team)
        self.stdout.write(f"Window {since.isoformat()} to {until.isoformat()}, wallet team {wallet_team}")
        self._section("Writer parity: settled compute_settled_usd vs gateway compute_usd", report.writer_parity)
        self._section(
            "Pricing parity: attributed sessions ended in window, priced live, vs gateway compute_usd",
            report.pricing_parity,
        )
        self._section(
            "Billing parity: billing aggregate for the window vs settled ledger amounts prorated to the window",
            report.billing_parity,
            tolerance_usd=CENT_ROUNDING_TOLERANCE_USD,
        )

    def _section(self, title: str, rows: tuple[TeamComputeDelta, ...], *, tolerance_usd: Decimal = Decimal(0)) -> None:
        self.stdout.write("")
        self.stdout.write(title)
        self.stdout.write(f"{'team':>12} {'local_usd':>14} {'gateway_usd':>14} {'delta_usd':>14} {'local_rows':>10}")
        for row in rows:
            line = (
                f"{row.team_id:>12} {row.local_usd:>14.6f} {row.gateway_usd:>14.6f} "
                f"{row.delta_usd:>14.6f} {row.local_rows:>10}"
            )
            self.stdout.write(self.style.WARNING(line) if abs(row.delta_usd) > tolerance_usd else line)
