import signal
import asyncio

from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.product_db_migrations import collect_unapplied_product_migrations, configured_product_databases
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.scheduling.runner import ShadowScheduler, ShadowSchedulerConfig
from products.warehouse_sources_queue.backend.sdk import HealthState, start_health_server

logger = structlog.get_logger(__name__)


async def _run_scheduler(config: ShadowSchedulerConfig, health_reporter) -> None:
    loop = asyncio.get_running_loop()
    shutdown = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)
    # Graceful shutdown: the loop finishes the in-flight tick and returns.
    await ShadowScheduler(config=config).run(shutdown, health_reporter)


class Command(BaseCommand):
    help = "Run the warehouse scheduler (shadow mode: records decisions, starts no syncs)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tick-interval",
            type=float,
            default=60.0,
            help="Seconds between scheduler ticks (default: 60.0)",
        )
        parser.add_argument(
            "--refresh-interval",
            type=float,
            default=300.0,
            help="Seconds between fleet-wide scope refreshes (default: 300.0)",
        )
        parser.add_argument(
            "--claim-limit",
            type=int,
            default=1000,
            help="Maximum due schemas claimed per tick (default: 1000)",
        )
        parser.add_argument(
            "--decision-retention-days",
            type=int,
            default=30,
            help="Days to keep shadow decisions before pruning (default: 30)",
        )
        parser.add_argument(
            "--health-port",
            type=int,
            default=8080,
            help="Port for the health check HTTP server (default: 8080)",
        )
        parser.add_argument(
            "--health-timeout",
            type=float,
            default=180.0,
            help="Health check timeout in seconds (default: 180.0)",
        )
        parser.add_argument(
            "--skip-migrations-check",
            action="store_true",
            help="Skip the startup check that the queue DB has this image's migrations applied (emergency escape hatch)",
        )

    def handle(self, *args, **options):
        # Same guard as run_warehouse_sources_load: an image that expects queue-DB
        # migrations the DB doesn't have would otherwise start and fail at runtime
        # (UndefinedTable), so refuse startup instead.
        if not options.get("skip_migrations_check"):
            if not configured_product_databases(databases={"warehouse_sources_queue"}):
                logger.warning(
                    "migrations_check_skipped_unconfigured",
                    note="PRODUCT_DB_WAREHOUSE_SOURCES_QUEUE_* env not set; queue schema not verified against this image",
                )
            unapplied = collect_unapplied_product_migrations(databases={"warehouse_sources_queue"})
            if unapplied:
                for alias, migrations in unapplied.items():
                    logger.error("unapplied_product_migrations", database_alias=alias, migrations=migrations)
                raise CommandError(
                    "Queue database is missing migrations this image expects: "
                    + "; ".join(f"{alias}: {', '.join(migrations)}" for alias, migrations in unapplied.items())
                )

        config = ShadowSchedulerConfig(
            database_url=WAREHOUSE_SOURCES_DATABASE_URL,
            tick_interval_seconds=options["tick_interval"],
            refresh_interval_seconds=options["refresh_interval"],
            claim_limit=options["claim_limit"],
            decision_retention_days=options["decision_retention_days"],
        )

        logger.info(
            "warehouse_scheduler_starting",
            tick_interval=config.tick_interval_seconds,
            refresh_interval=config.refresh_interval_seconds,
            claim_limit=config.claim_limit,
            decision_retention_days=config.decision_retention_days,
            health_port=options["health_port"],
        )

        health_state = HealthState(timeout_seconds=options["health_timeout"])
        start_health_server(port=options["health_port"], health_state=health_state)

        asyncio.run(_run_scheduler(config, health_state.report_healthy))
