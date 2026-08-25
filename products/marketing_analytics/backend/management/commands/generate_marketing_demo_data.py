"""Generate demo data for the Marketing analytics dashboard.

Creates a self-contained marketing world in the target project:

- $pageviews with correct, near-miss, and wrong UTMs across paid platforms,
  organic, direct, email, referral, and AI-assistant traffic
- conversion events (sign ups, purchases with revenue, demo bookings) with
  single- and multi-touch journeys, including out-of-window fallbacks
- cost tables in the warehouse using each platform's real column formats
  (Google micros + full ad hierarchy, Meta JSON actions, Bing unified report,
  plus a BigQuery-style table mapped via sources_map with EUR costs)
- ExternalDataSource/Schema/Job fixtures staging every Integration health
  state (ok, stale, error, never, tables missing/failed/disabled)
- team marketing config: conversion goals (healthy and deliberately broken),
  campaign name mappings, custom source mappings, field preferences
- the marketing feature flags at 100% rollout

Run against a dedicated local project: re-runs soft-delete and recreate the
demo sources/tables, but events accumulate.

Usage:
    DEBUG=1 python manage.py generate_marketing_demo_data --team-id 2
    DEBUG=1 python manage.py generate_marketing_demo_data --team-id 2 --days-past 90 --scale 0.5
    DEBUG=1 python manage.py generate_marketing_demo_data --team-id 2 --dry-run
"""

import tempfile
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models import Team
from posthog.settings import OBJECT_STORAGE_ACCESS_KEY_ID, OBJECT_STORAGE_SECRET_ACCESS_KEY

from products.marketing_analytics.backend.demo import (
    config as demo_config,
    health,
    warehouse,
)
from products.marketing_analytics.backend.demo.events import MarketingEventGenerator
from products.marketing_analytics.backend.demo.world import CAMPAIGNS, FREE_CHANNELS
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataSource,
    get_or_create_datawarehouse_credential,
)


class Command(BaseCommand):
    help = "Generate marketing analytics demo data (events, cost tables, health fixtures, config)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team (project) to seed into.")
        parser.add_argument("--seed", type=str, default="marketing-demo", help="Deterministic RNG seed.")
        parser.add_argument("--days-past", type=int, default=60, help="Days of history to generate (default: 60).")
        parser.add_argument("--scale", type=float, default=1.0, help="Traffic volume multiplier (default: 1.0).")
        parser.add_argument("--dry-run", action="store_true", help="Print the plan without writing anything.")
        parser.add_argument("--skip-events", action="store_true", help="Skip event generation (config/tables only).")
        parser.add_argument("--skip-flags", action="store_true", help="Skip enabling feature flags.")
        parser.add_argument(
            "--connect-all",
            action="store_true",
            help=(
                "Connect every staged ad platform, trading the connect_source case for full cost-table "
                "coverage. Organic-only platforms stay unconnected — they draw no suggestion either way."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Local-dev only: this seeder persists the deployment's OBJECT_STORAGE_*
        # key pair into a tenant-owned warehouse credential, which must never
        # happen against production object storage.
        if not settings.DEBUG:
            raise CommandError("This command is only for local development (requires DEBUG=1)")
        try:
            team = Team.objects.get(pk=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist")
        user = team.organization.members.first()
        if user is None:
            raise CommandError(f"Team {team.pk} has no organization members")

        if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_SECRET_ACCESS_KEY:
            raise CommandError("Object storage credentials are not configured (OBJECT_STORAGE_* settings)")

        days_past: int = options["days_past"]
        scale: float = options["scale"]
        now = timezone.now()

        if options["dry_run"]:
            self._print_plan(days_past, scale, connect_all=options["connect_all"])
            return

        # Ahead of the event write: the per-table check in `register_table` fires too late to keep a
        # wrong `--team-id` from leaving 48k events behind in ClickHouse.
        try:
            warehouse.assert_seedable(team)
        except ValueError as error:
            raise CommandError(str(error))

        generator = MarketingEventGenerator(team, seed=options["seed"], days_past=days_past, scale=scale, now=now)
        if options["skip_events"]:
            self.stdout.write("Skipping event generation.")
        else:
            self.stdout.write(f"Generating events for {days_past} days (scale {scale})...")
            generator.generate()
            self.stdout.write(self.style.SUCCESS(f"Wrote {generator.result.events_written} events to ClickHouse."))

        with tempfile.TemporaryDirectory(prefix="marketing-demo-") as tmp:
            out_dir = Path(tmp)
            builder = warehouse.CostTableBuilder(seed=options["seed"], days_past=days_past, now=now, out_dir=out_dir)

            self.stdout.write("Creating warehouse sources and staging Integration health states...")
            sources = health.create_sources(
                team, unconnected=frozenset() if options["connect_all"] else health.UNCONNECTED_PLATFORMS
            )
            credential = get_or_create_datawarehouse_credential(
                team_id=team.pk,
                access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
                access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            )

            self.stdout.write("Uploading cost tables for all native platforms...")
            table_map: dict[tuple[str, str], Any] = {}
            for platform, (builder_method, prefix, columns_by_schema) in warehouse.NATIVE_SPECS.items():
                if platform not in sources:  # unconnected: spend with nowhere to hang it
                    continue
                for schema_name, csv_path in getattr(builder, builder_method)().items():
                    registered = warehouse.register_table(
                        team,
                        csv_path=csv_path,
                        table_name=f"{prefix}_{schema_name}",
                        columns=columns_by_schema[schema_name],
                        source=sources[platform],
                        credential=credential,
                    )
                    table_map[(platform, schema_name)] = registered.table

            health.stage_schemas_and_jobs(team, sources, table_map)

            self.stdout.write("Uploading BigQuery-style ads table + Stripe-style invoices table...")
            ExternalDataSource.objects.filter(
                team=team, source_type="BigQuery", source_id="marketing-demo-bigquery"
            ).update(deleted=True)
            bigquery_source = ExternalDataSource.objects.create(
                team=team,
                source_id="marketing-demo-bigquery",
                connection_id="marketing-demo-bigquery",
                status=ExternalDataSource.Status.COMPLETED,
                source_type="BigQuery",
                prefix="",
            )
            ads_table = warehouse.register_table(
                team,
                csv_path=builder.build_bigquery_ads(),
                table_name=warehouse.BIGQUERY_ADS_TABLE,
                columns=warehouse.BIGQUERY_ADS_COLUMNS,
                source=bigquery_source,
                credential=credential,
            )
            # On --skip-events there are no fresh invoices; keep an existing
            # populated table instead of overwriting it with an empty one.
            invoices_table = None
            if options["skip_events"]:
                existing_invoices = DataWarehouseTable.objects.filter(
                    team=team, name=warehouse.STRIPE_INVOICES_TABLE, deleted=False
                ).first()
                if existing_invoices:
                    invoices_table = warehouse.RegisteredTable(
                        name=warehouse.STRIPE_INVOICES_TABLE, table=existing_invoices
                    )
            if invoices_table is None:
                invoices_table = warehouse.register_table(
                    team,
                    csv_path=builder.build_stripe_invoices(generator.result.invoices),
                    table_name=warehouse.STRIPE_INVOICES_TABLE,
                    columns=warehouse.STRIPE_INVOICES_COLUMNS,
                    source=bigquery_source,
                    credential=credential,
                )
            self.stdout.write(
                f"Registered {len(table_map) + 2} warehouse tables "
                f"({ads_table.name}, {invoices_table.name}, and native cost tables)."
            )

        bigquery_sources_map = {
            str(ads_table.table.id): {
                "id": "campaign_id",
                "campaign": "campaign_name",
                "source": "const:demo_partner",
                "date": "date",
                "cost": "cost",
                "clicks": "clicks",
                "impressions": "impressions",
                "currency": "const:EUR",
            }
        }
        self.stdout.write("Applying marketing analytics config (goals, mappings, attribution)...")
        demo_config.apply_marketing_config(team, bigquery_sources_map=bigquery_sources_map)

        if not options["skip_flags"]:
            enabled = demo_config.enable_feature_flags(team, user)
            self.stdout.write(f"Enabled {len(enabled)} feature flags.")

        self.stdout.write(self.style.SUCCESS("Done. Open /marketing in the target project."))
        self.stdout.write(
            "Kafka delivery is async: give ClickHouse a minute before expecting all events in the dashboard."
        )

    def _print_plan(self, days_past: int, scale: float, *, connect_all: bool) -> None:
        daily_sessions = sum(c.daily_sessions for c in CAMPAIGNS) + sum(c.daily_sessions for c in FREE_CHANNELS)
        self.stdout.write(f"Would generate ~{round(daily_sessions * scale)} sessions/day for {days_past} days:")
        for campaign in CAMPAIGNS:
            self.stdout.write(f"  [{campaign.platform}] {campaign.name}: {campaign.scenario or 'traffic'}")
        for channel in FREE_CHANNELS:
            self.stdout.write(f"  [free] {channel.key}: {channel.scenario or 'traffic'}")
        # Mirror the real run's source of truth so the summary matches what --connect-all creates.
        unconnected = frozenset() if connect_all else health.UNCONNECTED_PLATFORMS
        native_tables = sum(
            len(columns)
            for platform, (_method, _prefix, columns) in warehouse.NATIVE_SPECS.items()
            if platform not in unconnected
        )
        connected = len(health.PLATFORM_STATES) - len(unconnected)
        # A platform reaches events_only whenever it has no source and its utm_source
        # matches, so the organic-only ones count too even though `--connect-all` never
        # touches them. Only the paid half draws connect_source; the gate suppresses the rest.
        drawing = ", ".join(sorted(unconnected)) or "none"
        suppressed = ", ".join(sorted(health.ORGANIC_ONLY_PLATFORMS)) or "none"
        events_only = len(unconnected) + len(health.ORGANIC_ONLY_PLATFORMS)
        self.stdout.write(
            f"Plus: health fixtures for {connected} connected platforms, "
            f"{events_only} in events_only ({drawing} draw connect_source; "
            f"{suppressed} organic-only, suppressed by the paid gate), "
            f"{native_tables + 2} warehouse tables, conversion goals, flags."
        )
