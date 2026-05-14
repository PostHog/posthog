"""One-shot demo seeder for the uptime product.

Creates a realistic-looking set of monitors (mix of auto and manual), a published
status page wiring them up, and a handful of declared incidents — enough that a
fresh local stack has a non-empty Monitors tab, Incidents tab, and a working
public status page to share.

Idempotent: every entity is keyed off a "Demo: " name prefix and re-running the
command skips anything already in place. Pass --purge to wipe the demo state
first if you want a clean slate.

Pair with --with-pings to also backfill historical ping data via
`seed_uptime_pings`, so the 90-day status timeline isn't blank for the first
few minutes after the rust pinger comes up.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models.scoping import team_scope

from products.uptime.backend.facade import (
    api as facade_api,
    contracts,
)
from products.uptime.backend.models import Incident, Monitor, StatusPage

DEMO_NAME_PREFIX = "Demo: "

DEMO_MONITORS: list[dict[str, Any]] = [
    {
        "name": "Demo: Marketing site",
        "url": "https://posthog.com",
        "mode": "auto",
    },
    {
        "name": "Demo: App",
        "url": "https://app.posthog.com",
        "mode": "auto",
    },
    {
        "name": "Demo: Payments processor",
        "url": None,
        "mode": "manual",
    },
]

DEMO_STATUS_PAGE_TITLE = "Demo: PostHog public status"
DEMO_STATUS_PAGE_SLUG = "demo-posthog-status"


class Command(BaseCommand):
    help = "Seed the uptime product with demo monitors, incidents, and a status page."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            default=1,
            help="Team ID to seed (default: 1, the first team in local dev)",
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Delete existing demo monitors / incidents / status page before seeding.",
        )
        parser.add_argument(
            "--with-pings",
            action="store_true",
            help="Also run seed_uptime_pings afterwards to backfill 90 days of historical pings.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        purge: bool = options["purge"]
        with_pings: bool = options["with_pings"]

        with team_scope(team_id):
            if purge:
                self._purge_demo(team_id)
            monitor_ids = self._seed_monitors(team_id)
            self._seed_incidents(team_id, monitor_ids)
            self._seed_status_page(team_id, monitor_ids)

        if with_pings:
            self.stdout.write("Backfilling 90 days of historical pings...")
            # Calls into ClickHouse via the existing seed command. We do this outside
            # the team_scope block because seed_uptime_pings opens its own scope.
            call_command("seed_uptime_pings", team_id=team_id, days=90)

        self.stdout.write(self.style.SUCCESS("Demo seeded. Open the Uptime tab to see it."))

    def _purge_demo(self, team_id: int) -> None:
        page_count, _ = StatusPage.objects.filter(team_id=team_id, title=DEMO_STATUS_PAGE_TITLE).delete()
        # Incidents cascade off Monitor.on_delete, but we delete them explicitly first so
        # the count reported below is meaningful.
        incident_qs = Incident.objects.filter(team_id=team_id, monitor__name__startswith=DEMO_NAME_PREFIX)
        incident_count, _ = incident_qs.delete()
        monitor_count, _ = Monitor.objects.filter(team_id=team_id, name__startswith=DEMO_NAME_PREFIX).delete()
        self.stdout.write(
            f"Purged {monitor_count} monitor(s), {incident_count} incident(s), {page_count} status page(s)."
        )

    def _seed_monitors(self, team_id: int) -> dict[str, UUID]:
        """Create demo monitors keyed by name. Returns name → monitor_id."""
        existing = {m.name: m.id for m in Monitor.objects.filter(team_id=team_id, name__startswith=DEMO_NAME_PREFIX)}
        out: dict[str, UUID] = {}
        for spec in DEMO_MONITORS:
            name = spec["name"]
            if name in existing:
                out[name] = existing[name]
                self.stdout.write(f"  Monitor exists: {name}")
                continue
            dto = facade_api.create(
                contracts.CreateMonitorInput(
                    team_id=team_id,
                    name=name,
                    url=spec["url"],
                    mode=spec["mode"],
                )
            )
            out[name] = dto.id
            self.stdout.write(f"  Created monitor: {name} ({spec['mode']})")
        return out

    def _seed_incidents(self, team_id: int, monitor_ids: dict[str, UUID]) -> None:
        """Three incidents that show off different states the UI handles."""
        now = timezone.now()
        existing_incident_names = set(
            Incident.objects.filter(team_id=team_id, monitor__name__startswith=DEMO_NAME_PREFIX).values_list(
                "name", flat=True
            )
        )

        incidents: list[contracts.CreateIncidentInput] = [
            # Resolved a few weeks back — gives the timeline a "down" day in the past.
            contracts.CreateIncidentInput(
                team_id=team_id,
                monitor_id=monitor_ids["Demo: App"],
                name="Login latency spike",
                description="Investigating elevated latency on the login endpoint in us-east-1.",
                started_at=now - timedelta(days=18, hours=4),
                resolved_at=now - timedelta(days=18, hours=2),
                resolution_note="Root cause was a hot Postgres connection pool. Pool size increased; rolled forward.",
            ),
            # Recently resolved on the manual monitor — exercises the manual incident path.
            contracts.CreateIncidentInput(
                team_id=team_id,
                monitor_id=monitor_ids["Demo: Payments processor"],
                name="Stripe webhook delays",
                description="Stripe acknowledged elevated webhook delivery delays affecting subscription updates.",
                started_at=now - timedelta(days=2, hours=6),
                resolved_at=now - timedelta(days=2, hours=1),
                resolution_note="Stripe restored webhook delivery. No data loss; we caught up via reconciliation.",
            ),
            # Ongoing so the Incidents tab has a non-zero badge for the demo.
            contracts.CreateIncidentInput(
                team_id=team_id,
                monitor_id=monitor_ids["Demo: Marketing site"],
                name="CDN cache misses in EU",
                description="Some EU edge nodes are bypassing cache and going to origin. Investigating with Cloudflare.",
                started_at=now - timedelta(hours=3),
            ),
        ]

        for incident_input in incidents:
            if incident_input.name in existing_incident_names:
                self.stdout.write(f"  Incident exists: {incident_input.name}")
                continue
            facade_api.create_incident(incident_input)
            state = "ongoing" if incident_input.resolved_at is None else "resolved"
            self.stdout.write(f"  Created incident: {incident_input.name} ({state})")

    def _seed_status_page(self, team_id: int, monitor_ids: dict[str, UUID]) -> None:
        existing = StatusPage.objects.filter(team_id=team_id, title=DEMO_STATUS_PAGE_TITLE).first()
        if existing:
            self.stdout.write(f"  Status page exists: {DEMO_STATUS_PAGE_TITLE}")
            return
        try:
            page = facade_api.create_status_page(team_id=team_id)
        except Exception as exc:
            raise CommandError(f"Failed to create status page: {exc}") from exc

        ordered_ids = [
            monitor_ids[name]
            for name in (
                "Demo: Marketing site",
                "Demo: App",
                "Demo: Payments processor",
            )
        ]
        facade_api.update_status_page(
            contracts.UpdateStatusPageInput(
                team_id=team_id,
                page_id=page.id,
                title=DEMO_STATUS_PAGE_TITLE,
                slug=DEMO_STATUS_PAGE_SLUG,
                monitor_ids=ordered_ids,
            )
        )
        facade_api.publish_status_page(team_id=team_id, page_id=page.id)
        self.stdout.write(f"  Created and published status page at /status/{DEMO_STATUS_PAGE_SLUG}")
