import asyncio

from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.product_db_migrations import collect_unapplied_product_migrations, configured_product_databases
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.common.logger import configure_logger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import (
    configure_process_concurrency,
)
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
from products.warehouse_sources_queue.backend.models import SourceBatch

logger = structlog.get_logger(__name__)


def parse_sync_types(raw: str | None, flag: str) -> list[str] | None:
    """Parse a comma-separated sync-type list, validated against SourceBatch.SyncType."""
    if raw is None:
        return None
    values = [value.strip() for value in raw.split(",") if value.strip()]
    if not values:
        return None
    valid = set(SourceBatch.SyncType.values)
    invalid = [value for value in values if value not in valid]
    if invalid:
        raise CommandError(f"{flag}: unknown sync type(s) {invalid}; valid: {sorted(valid)}")
    return values


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


async def _run_consumer(
    config: ConsumerConfig,
    health_reporter,
    claim_sync_types: list[str] | None,
    claim_exclude_sync_types: list[str] | None,
) -> None:
    """Configure the Temporal-style produce path then run the consumer.

    `configure_logger` plumbs structlog into a Kafka producer that feeds ClickHouse `log_entries`.
    Calling it from the consumer's own asyncio loop is the same pattern `start_temporal_worker` uses;
    `merge_temporal_context` no-ops outside an actual workflow/activity, and the per-batch contextvars
    set in `BatchConsumer._process_single` carry the keys `LogMessagesRenderer` needs (`workflow_type`,
    `workflow_id`, `workflow_run_id`, `team_id`, plus the event-level `log_source_id` override).
    """
    configure_logger(loop=asyncio.get_running_loop())
    consumer = BatchConsumer(
        config=config,
        process_batch=process_batch,
        health_reporter=health_reporter,
        claim_sync_types=claim_sync_types,
        claim_exclude_sync_types=claim_exclude_sync_types,
    )
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
        # Deprecated no-op kept so deploys still passing the flag don't crash;
        # the legacy status-log claim path was removed and 'state' is the only reader.
        parser.add_argument(
            "--claim-path",
            choices=["legacy", "state"],
            default=None,
            help="Deprecated, ignored: readers always use the denormalized state columns",
        )
        # Fleet partitioning: which sourcebatch.sync_type classes this deployment claims
        # and sweeps. Paired deployments must cover every class between them — a class no
        # fleet claims sits in the queue until partition pruning.
        parser.add_argument(
            "--claim-sync-types",
            type=str,
            default=None,
            help="Comma-separated sync types this consumer claims (e.g. 'cdc'). Default: all",
        )
        parser.add_argument(
            "--skip-migrations-check",
            action="store_true",
            help="Skip the startup check that the queue DB has this image's migrations applied (emergency escape hatch)",
        )
        parser.add_argument(
            "--claim-exclude-sync-types",
            type=str,
            default=None,
            help=(
                "Comma-separated sync types this consumer does NOT claim (e.g. 'cdc'). "
                "Mutually exclusive with --claim-sync-types"
            ),
        )

    def handle(self, *args, **options):
        # Defense-in-depth behind the wave-1 ArgoCD migration-check hook: an image
        # that expects queue-DB migrations the DB doesn't have would otherwise start
        # and fail at runtime (UndefinedColumn), so refuse startup instead. Requires
        # the PRODUCT_DB_WAREHOUSE_SOURCES_QUEUE_* env (a no-op where it is absent).
        if not options.get("skip_migrations_check"):
            if not configured_product_databases(databases={"warehouse_sources_queue"}):
                # Legacy config: consumer reaches the queue DB via WAREHOUSE_SOURCES_DATABASE_URL
                # alone, so the schema can't be verified. Warn instead of failing so those
                # deployments keep working, but make the blind spot visible to operators.
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

        health_port = options["health_port"]
        health_timeout = options["health_timeout"]

        config = build_consumer_config(options)

        # Size deltalite's per-upsert memory slices against this loader's real concurrency (its own
        # max_concurrency), since it is a Kafka consumer, not a Temporal worker, so the governor's
        # MAX_CONCURRENT_ACTIVITIES source of truth is unset here.
        configure_process_concurrency(config.max_concurrency)

        if options.get("claim_path") == "legacy":
            logger.warning(
                "claim_path_legacy_removed", note="--claim-path is ignored; the legacy claim path no longer exists"
            )

        claim_sync_types = parse_sync_types(options.get("claim_sync_types"), "--claim-sync-types")
        claim_exclude_sync_types = parse_sync_types(
            options.get("claim_exclude_sync_types"), "--claim-exclude-sync-types"
        )
        if claim_sync_types and claim_exclude_sync_types:
            raise CommandError("--claim-sync-types and --claim-exclude-sync-types are mutually exclusive")

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
            poll_failure_liveness_threshold=config.poll_failure_liveness_threshold,
            claim_sync_types=claim_sync_types,
            claim_exclude_sync_types=claim_exclude_sync_types,
        )

        health_state = HealthState(timeout_seconds=health_timeout)
        start_health_server(port=health_port, health_state=health_state)

        asyncio.run(_run_consumer(config, health_state.report_healthy, claim_sync_types, claim_exclude_sync_types))
