import asyncio

from django.core.management.base import BaseCommand

import structlog

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.common.logger import configure_logger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer import (
    DuckgresBatchConsumer,
    DuckgresConsumerConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.load import process_batch
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.health import (
    HealthState,
    start_health_server,
)

logger = structlog.get_logger(__name__)

# The sink exists to survive duckgres maintenance windows: defaults give ~3h of
# retry coverage (8 attempts, 300s * attempt backoff) instead of the engine's
# <2min, because a max-attempts failure permanently gaps incremental tables.
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_RETRY_BACKOFF_SECONDS = 300
# A duckgres MERGE can legitimately run for minutes; recovery must not hand the
# batch to another pod while the first is still writing.
DEFAULT_RECOVERY_GRACE_SECONDS = 900
# A single batch wedged longer than this fails liveness so the pod restarts and
# the recovery sweep reassigns the batch.
DEFAULT_STUCK_BATCH_TIMEOUT_SECONDS = 1800.0


class Command(BaseCommand):
    help = "Run the warehouse sources Duckgres batch consumer"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-concurrency",
            type=int,
            default=16,
            help="Maximum number of (team_id, schema_id) groups processed concurrently (default: 16)",
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=2.0,
            help="Seconds between poll cycles when idle (default: 2.0)",
        )
        parser.add_argument(
            "--poll-limit",
            type=int,
            default=50,
            help="Maximum batches fetched per poll cycle (default: 50)",
        )
        parser.add_argument(
            "--max-attempts",
            type=int,
            default=DEFAULT_MAX_ATTEMPTS,
            help=f"Maximum processing attempts per batch before failing the Duckgres run (default: {DEFAULT_MAX_ATTEMPTS})",
        )
        parser.add_argument(
            "--retry-backoff",
            type=int,
            default=DEFAULT_RETRY_BACKOFF_SECONDS,
            help=f"Base seconds of retry backoff, multiplied by attempt (default: {DEFAULT_RETRY_BACKOFF_SECONDS})",
        )
        parser.add_argument(
            "--recovery-grace",
            type=int,
            default=DEFAULT_RECOVERY_GRACE_SECONDS,
            help=f"Seconds an 'executing' batch must be stale before recovery reassigns it (default: {DEFAULT_RECOVERY_GRACE_SECONDS})",
        )
        parser.add_argument(
            "--stuck-batch-timeout",
            type=float,
            default=DEFAULT_STUCK_BATCH_TIMEOUT_SECONDS,
            help=f"Seconds a single batch may run before the pod stops reporting healthy (default: {DEFAULT_STUCK_BATCH_TIMEOUT_SECONDS})",
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
            default=60.0,
            help="Health check timeout in seconds (default: 60.0)",
        )

    def handle(self, *args, **options):
        health_port = options["health_port"]
        health_timeout = options["health_timeout"]

        config = DuckgresConsumerConfig(
            database_url=WAREHOUSE_SOURCES_DATABASE_URL,
            max_concurrency=options["max_concurrency"],
            poll_interval_seconds=options["poll_interval"],
            poll_limit=options["poll_limit"],
            max_attempts=options["max_attempts"],
            retry_backoff_base_seconds=options["retry_backoff"],
            recovery_grace_seconds=options["recovery_grace"],
            stuck_batch_timeout_seconds=options["stuck_batch_timeout"],
            health_port=health_port,
            health_timeout_seconds=health_timeout,
        )

        logger.info(
            "warehouse_sources_duckgres_load_starting",
            max_concurrency=config.max_concurrency,
            poll_interval=config.poll_interval_seconds,
            poll_limit=config.poll_limit,
            max_attempts=config.max_attempts,
            retry_backoff_base_seconds=config.retry_backoff_base_seconds,
            recovery_grace_seconds=config.recovery_grace_seconds,
            stuck_batch_timeout_seconds=config.stuck_batch_timeout_seconds,
            health_port=health_port,
        )

        health_state = HealthState(timeout_seconds=health_timeout)
        start_health_server(port=health_port, health_state=health_state)

        consumer = DuckgresBatchConsumer(
            config=config, process_batch=process_batch, health_reporter=health_state.report_healthy
        )
        asyncio.run(_run_consumer(consumer))


async def _run_consumer(consumer: DuckgresBatchConsumer) -> None:
    # Route structlog through the Kafka -> ClickHouse log_entries pipeline so the
    # per-batch contextvars the engine binds are user-visible, mirroring the Delta
    # consumer's entrypoint.
    configure_logger(loop=asyncio.get_running_loop())
    await consumer.run()
