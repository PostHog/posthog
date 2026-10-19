import asyncio
from collections.abc import Callable
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import structlog

from posthog.product_db_migrations import collect_unapplied_product_migrations, configured_product_databases
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.common.logger import configure_logger

from products.warehouse_sources.backend.queue_runs.budgets import CONSUMER_MAX_ATTEMPTS
from products.warehouse_sources.backend.queue_runs.claim_gate import MemoryClaimGate
from products.warehouse_sources.backend.queue_runs.extract_handler import ExtractHandlerConfig, SyncExtractHandler
from products.warehouse_sources.backend.queue_runs.payloads import EXTRACT_LANE, SYNC_EXTRACT_KIND
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import (
    configure_process_concurrency,
)
from products.warehouse_sources_queue.backend.sdk import (
    BatchConsumerConfig,
    HealthState,
    JobConsumer,
    start_health_server,
)

logger = structlog.get_logger(__name__)

# The handler needs this long before the drain ends to return its shutdown retry.
SHUTDOWN_RETURN_MARGIN_SECONDS = 60.0


def build_consumer_config(options: dict[str, Any]) -> BatchConsumerConfig:
    return BatchConsumerConfig(
        database_url=WAREHOUSE_SOURCES_DATABASE_URL,
        max_concurrency=options["max_concurrency"],
        poll_interval_seconds=options["poll_interval"],
        poll_limit=options["poll_limit"],
        max_attempts=CONSUMER_MAX_ATTEMPTS,
        health_port=options["health_port"],
        health_timeout_seconds=options["health_timeout"],
        shutdown_drain_timeout_seconds=options["drain_timeout"],
        # A run executes for hours inside one job, so a long job is not a stuck one.
        stuck_batch_timeout_seconds=None,
    )


def build_handler_config(options: dict[str, Any]) -> ExtractHandlerConfig:
    return ExtractHandlerConfig(
        shutdown_grace_seconds=max(options["drain_timeout"] - SHUTDOWN_RETURN_MARGIN_SECONDS, 0.0),
    )


async def _run_consumer(
    config: BatchConsumerConfig,
    handler_config: ExtractHandlerConfig,
    health_reporter: Callable[[], None],
    claim_gate: Callable[[], bool] | None,
) -> None:
    # Same log setup as the load consumer: the handler binds the keys the log renderer needs,
    # so run logs reach the schema's log stream as they do from a Temporal activity.
    configure_logger(loop=asyncio.get_running_loop())
    consumer = JobConsumer(
        config=config,
        lane=EXTRACT_LANE,
        handlers={SYNC_EXTRACT_KIND: SyncExtractHandler(config=handler_config)},
        health_reporter=health_reporter,
        claim_gate=claim_gate,
    )
    await consumer.run()


class Command(BaseCommand):
    help = "Run the warehouse extract consumer (sync.extract jobs on the extract lane)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--max-concurrency",
            type=int,
            default=4,
            help="Maximum number of schemas extracted at the same time (default: 4)",
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=10.0,
            help="Seconds between poll cycles (default: 10.0)",
        )
        parser.add_argument(
            "--poll-limit",
            type=int,
            default=10,
            help="Maximum jobs fetched per poll cycle (default: 10)",
        )
        parser.add_argument(
            "--drain-timeout",
            type=float,
            default=600.0,
            help=(
                "Seconds a shutdown waits for in-flight runs before it cancels them. Set the pod's "
                "terminationGracePeriodSeconds above this value (default: 600.0)"
            ),
        )
        parser.add_argument(
            "--min-free-memory-mb",
            type=float,
            default=0.0,
            help="Claim no job while the pod has less free memory than this. 0 disables the gate (default: 0)",
        )
        parser.add_argument(
            "--health-port",
            type=int,
            default=8080,
            help="Port for the health check and metrics HTTP server (default: 8080)",
        )
        parser.add_argument(
            "--health-timeout",
            type=float,
            default=60.0,
            help="Health check timeout in seconds (default: 60.0)",
        )
        parser.add_argument(
            "--skip-migrations-check",
            action="store_true",
            help="Skip the startup check that the queue DB has this image's migrations applied (emergency escape hatch)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Same guard as run_warehouse_sources_load: refuse to start against a queue DB that is
        # missing migrations this image expects.
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

        if options["max_concurrency"] < 1:
            raise CommandError("--max-concurrency must be at least 1")

        config = build_consumer_config(options)
        handler_config = build_handler_config(options)
        min_free_mb = options["min_free_memory_mb"]
        claim_gate = MemoryClaimGate(min_free_mb=min_free_mb) if min_free_mb > 0 else None

        # Each run's Delta writes size their memory slices against this process's real concurrency.
        configure_process_concurrency(config.max_concurrency)

        logger.info(
            "warehouse_extract_consumer_starting",
            max_concurrency=config.max_concurrency,
            poll_interval=config.poll_interval_seconds,
            poll_limit=config.poll_limit,
            max_attempts=config.max_attempts,
            drain_timeout=config.shutdown_drain_timeout_seconds,
            shutdown_grace=handler_config.shutdown_grace_seconds,
            min_free_memory_mb=min_free_mb,
            health_port=config.health_port,
        )

        health_state = HealthState(timeout_seconds=config.health_timeout_seconds)
        start_health_server(port=config.health_port, health_state=health_state)

        asyncio.run(_run_consumer(config, handler_config, health_state.report_healthy, claim_gate))
