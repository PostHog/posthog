import asyncio

from django.core.management.base import BaseCommand

import structlog

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.common.logger import configure_logger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.health import (
    HealthState,
    start_health_server,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (
    BatchConsumer,
    ConsumerConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.load import (
    process_batch,
)

logger = structlog.get_logger(__name__)


async def _run_consumer(config: ConsumerConfig, health_reporter) -> None:
    """Configure the Temporal-style produce path then run the consumer.

    `configure_logger` plumbs structlog into a Kafka producer that feeds ClickHouse `log_entries`.
    Calling it from the consumer's own asyncio loop is the same pattern `start_temporal_worker` uses;
    `merge_temporal_context` no-ops outside an actual workflow/activity, and the per-batch contextvars
    set in `BatchConsumer._process_single` carry the keys `LogMessagesRenderer` needs (`workflow_type`,
    `workflow_id`, `workflow_run_id`, `team_id`, plus the event-level `log_source_id` override).
    """
    configure_logger(loop=asyncio.get_running_loop())
    consumer = BatchConsumer(config=config, process_batch=process_batch, health_reporter=health_reporter)
    await consumer.run()


class Command(BaseCommand):
    help = "Run the warehouse sources batch consumer"

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
            default=3,
            help="Maximum processing attempts per batch before failing the run (default: 3)",
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

        config = ConsumerConfig(
            database_url=WAREHOUSE_SOURCES_DATABASE_URL,
            max_concurrency=options["max_concurrency"],
            poll_interval_seconds=options["poll_interval"],
            poll_limit=options["poll_limit"],
            max_attempts=options["max_attempts"],
            health_port=health_port,
            health_timeout_seconds=health_timeout,
        )

        logger.info(
            "warehouse_sources_load_starting",
            max_concurrency=config.max_concurrency,
            poll_interval=config.poll_interval_seconds,
            poll_limit=config.poll_limit,
            max_attempts=config.max_attempts,
            health_port=health_port,
        )

        health_state = HealthState(timeout_seconds=health_timeout)
        start_health_server(port=health_port, health_state=health_state)

        asyncio.run(_run_consumer(config, health_state.report_healthy))
