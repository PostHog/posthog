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


def build_consumer_config(options: dict) -> ConsumerConfig:
    """Translate CLI options into a ConsumerConfig.

    Ceiling flags map 0 to None (disabled); unset flags keep the dataclass defaults.
    """
    kwargs: dict = {
        "database_url": WAREHOUSE_SOURCES_DATABASE_URL,
        "max_concurrency": options["max_concurrency"],
        "poll_interval_seconds": options["poll_interval"],
        "poll_limit": options["poll_limit"],
        "max_attempts": options["max_attempts"],
        "health_port": options["health_port"],
        "health_timeout_seconds": options["health_timeout"],
        "stuck_batch_timeout_seconds": options["stuck_batch_timeout"] or None,
    }
    if options.get("poll_timeout") is not None:
        kwargs["poll_timeout_seconds"] = options["poll_timeout"] or None
    if options.get("sweep_timeout") is not None:
        kwargs["sweep_timeout_seconds"] = options["sweep_timeout"] or None
    if options.get("connect_timeout") is not None:
        kwargs["connect_timeout_seconds"] = options["connect_timeout"]
    if options.get("lease_ttl") is not None:
        kwargs["lease_ttl_seconds"] = options["lease_ttl"]
    if options.get("recovery_grace") is not None:
        kwargs["recovery_grace_seconds"] = options["recovery_grace"]
    if options.get("poll_failure_liveness_threshold") is not None:
        kwargs["poll_failure_liveness_threshold"] = options["poll_failure_liveness_threshold"] or None
    return ConsumerConfig(**kwargs)


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
        parser.add_argument(
            "--stuck-batch-timeout",
            type=float,
            default=7200.0,
            help=(
                "Stop reporting liveness once any single batch has been executing longer than this many "
                "seconds, so a wedged sink connection becomes a pod restart instead of an invisible stall. "
                "0 disables the watchdog (default: 7200.0)"
            ),
        )
        # Omitted flags keep the ConsumerConfig defaults (single source of truth);
        # exposed so a degraded fleet can be retuned without a code deploy.
        parser.add_argument(
            "--poll-timeout",
            type=float,
            default=None,
            help="Seconds before a claim poll is abandoned and retried on a fresh connection. 0 disables the ceiling",
        )
        parser.add_argument(
            "--sweep-timeout",
            type=float,
            default=None,
            help="Seconds before a recovery/reconcile sweep is abandoned. 0 disables the ceiling",
        )
        parser.add_argument(
            "--connect-timeout",
            type=int,
            default=None,
            help="Seconds before a queue-DB connection attempt fails",
        )
        parser.add_argument(
            "--lease-ttl",
            type=int,
            default=None,
            help="Group-lease validity window in seconds (defaults to --recovery-grace)",
        )
        parser.add_argument(
            "--recovery-grace",
            type=int,
            default=None,
            help="Seconds an executing batch may go without a heartbeat before the recovery sweep re-queues it",
        )
        parser.add_argument(
            "--poll-failure-liveness-threshold",
            type=int,
            default=None,
            help=(
                "Stop reporting liveness after this many consecutive failed polls, so a pod that can no "
                "longer claim work becomes a visible restart instead of a silent zero-throughput loop. "
                "0 disables the trip"
            ),
        )

    def handle(self, *args, **options):
        health_port = options["health_port"]
        health_timeout = options["health_timeout"]

        config = build_consumer_config(options)

        logger.info(
            "warehouse_sources_load_starting",
            max_concurrency=config.max_concurrency,
            poll_interval=config.poll_interval_seconds,
            poll_limit=config.poll_limit,
            max_attempts=config.max_attempts,
            health_port=health_port,
            stuck_batch_timeout=config.stuck_batch_timeout_seconds,
            poll_timeout=config.poll_timeout_seconds,
            sweep_timeout=config.sweep_timeout_seconds,
            connect_timeout=config.connect_timeout_seconds,
            lease_ttl=config.lease_ttl_seconds,
            recovery_grace=config.recovery_grace_seconds,
        )

        health_state = HealthState(timeout_seconds=health_timeout)
        start_health_server(port=health_port, health_state=health_state)

        asyncio.run(_run_consumer(config, health_state.report_healthy))
