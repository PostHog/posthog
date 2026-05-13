"""Seed synthetic uptime_pings rows so the uptime UI looks alive in local dev.

For each monitor in the chosen team, inserts pings every ~5 minutes for the last N days
with a tunable failure rate. A small fraction of monitors get an "incident" window
(one or more days with elevated failures) so the status timeline shows real variation.
"""

import uuid
import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client import sync_execute
from posthog.models.scoping import team_scope

from products.uptime.backend.facade.enums import PingOutcome
from products.uptime.backend.models import Monitor


class Command(BaseCommand):
    help = "Seed uptime_pings rows for every monitor in a team so the UI has realistic data."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID whose monitors should get pings")
        parser.add_argument("--days", type=int, default=30, help="Spread pings across the last N days")
        parser.add_argument("--interval-minutes", type=int, default=5, help="Spacing between pings")
        parser.add_argument(
            "--failure-rate",
            type=float,
            default=0.01,
            help="Baseline probability that any given ping fails (0..1)",
        )
        parser.add_argument(
            "--incident-monitors",
            type=int,
            default=1,
            help="Number of monitors that get an extended incident window for realism",
        )
        parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for deterministic output")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        days: int = options["days"]
        interval_minutes: int = options["interval_minutes"]
        failure_rate: float = options["failure_rate"]
        n_incidents: int = options["incident_monitors"]
        rng_seed: int | None = options["seed"]

        with team_scope(team_id):
            monitors = list(Monitor.objects.filter(team_id=team_id))
        if not monitors:
            raise CommandError(f"Team {team_id} has no monitors. Create some first.")

        rng = random.Random(rng_seed)

        # Pick a few monitors to get an incident window (single day with many failures)
        incident_monitor_ids: set[uuid.UUID] = set(
            rng.sample([m.id for m in monitors], k=min(n_incidents, len(monitors)))
        )
        incident_day_offset = rng.randint(2, max(2, days - 2))

        now = datetime.now(tz=ZoneInfo("UTC"))
        window_start = now - timedelta(days=days)

        self.stdout.write(
            f"Seeding pings for {len(monitors)} monitor(s) over {days}d at ~{interval_minutes}m intervals..."
        )

        rows_to_insert: list[dict] = []
        for monitor in monitors:
            timestamp = window_start
            incident_today = monitor.id in incident_monitor_ids
            while timestamp <= now:
                in_incident_window = incident_today and abs((now - timestamp).days - incident_day_offset) == 0
                effective_failure_rate = 0.6 if in_incident_window else failure_rate
                outcome = PingOutcome.FAILURE if rng.random() < effective_failure_rate else PingOutcome.SUCCESS

                if outcome == PingOutcome.SUCCESS:
                    latency_ms = rng.randint(60, 350)
                    status_code = 200
                else:
                    latency_ms = rng.randint(2_000, 10_000)
                    status_code = rng.choice([0, 500, 502, 503, 504])

                rows_to_insert.append(
                    {
                        "team_id": team_id,
                        "monitor_id": str(monitor.id),
                        "timestamp": timestamp,
                        "latency_ms": latency_ms,
                        "status_code": status_code,
                        "outcome": outcome.value,
                    }
                )
                # Slight jitter so timestamps aren't on a perfect grid
                jitter = rng.randint(-30, 30)
                timestamp += timedelta(minutes=interval_minutes, seconds=jitter)

        # Single bulk insert — much faster than one statement per row
        if rows_to_insert:
            sync_execute(
                """
                INSERT INTO uptime_pings
                (team_id, monitor_id, timestamp, latency_ms, status_code, outcome)
                VALUES
                """,
                rows_to_insert,
            )

        self.stdout.write(self.style.SUCCESS(f"Inserted {len(rows_to_insert)} pings across {len(monitors)} monitors."))
