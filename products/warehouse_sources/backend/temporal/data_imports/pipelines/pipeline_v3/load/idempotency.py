from contextlib import contextmanager

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client
from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter

logger = structlog.get_logger(__name__)

IDEMPOTENCY_KEY_PREFIX = "warehouse_pipelines:processed"
IDEMPOTENCY_TTL_SECONDS = 72 * 60 * 60  # 3 days (72 hours) same as the topic retention period


@contextmanager
def get_redis_client():
    """Get a Redis client for the data warehouse Redis instance."""
    redis_client = None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for warehouse pipelines: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis_client = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        redis_client.ping()
    except Exception as e:
        logger.warning(
            "Redis unavailable for idempotency check — falling back to delta history scan",
            error=str(e),
        )
        capture_exception(e)
        redis_client = None

    try:
        yield redis_client
    finally:
        pass


def get_idempotency_key(
    team_id: int, schema_id: str, run_uuid: str, batch_index: int, destination_id: str | None = None
) -> str:
    """Generate a unique idempotency key for a batch at one destination.

    The PostHog warehouse keeps the unsuffixed key it has always used, so keys written
    before this change still match after a deploy. Every other destination gets its own,
    which is what lets a retry skip the destinations that already took the batch instead
    of re-writing all of them.
    """
    base = f"{IDEMPOTENCY_KEY_PREFIX}:{team_id}:{schema_id}:{run_uuid}:{batch_index}"
    return base if destination_id is None else f"{base}:{destination_id}"


def is_batch_already_processed(
    team_id: int,
    schema_id: str,
    run_uuid: str,
    batch_index: int,
    delta_table_ref: DeltaTableRef | None = None,
    destination_id: str | None = None,
    *,
    is_first_attempt: bool = False,
) -> bool:
    """Check if a batch has already been processed.

    Fast path: the Redis dedup flag written by `mark_batch_as_processed` after a
    successful delta write.

    Slow path (post-crash recovery): if Redis has no flag and a `DeltaTableRef`
    is provided, scan recent delta commits for a commit whose userMetadata matches
    this (run_uuid, batch_index). This catches the narrow writer-crash window
    between `DeltaWriter.write` committing and `mark_batch_as_processed` running —
    on Kafka redelivery we'd otherwise re-write the same batch and produce
    duplicate rows.

    `is_first_attempt` skips that slow path. A batch that has never been delivered has
    no earlier write to find, so the scan can only answer "no" — and it is not cheap:
    it opens the table and reads the last 50 commits, both of which grow with the
    table's file count, so a long first sync pays more for it on every batch. The skip
    applies only when Redis answered: a Redis outage leaves the fast path inconclusive,
    and the scan is then the only protection against a duplicate write.
    """
    with get_redis_client() as redis_client:
        if redis_client is not None:
            key = get_idempotency_key(team_id, schema_id, run_uuid, batch_index, destination_id)
            if redis_client.exists(key) == 1:
                return True
            if is_first_attempt:
                return False

    if delta_table_ref is None:
        return False

    try:
        return async_to_sync(DeltaWriter(delta_table_ref).has_batch_been_committed)(run_uuid, batch_index)
    except Exception as e:
        # Failing open here would re-enable the duplicate-write race we're fixing,
        # so we log and surface the error to the caller (which will retry the message).
        logger.warning(
            "delta_history_idempotency_check_failed",
            team_id=team_id,
            schema_id=schema_id,
            run_uuid=run_uuid,
            batch_index=batch_index,
            error=str(e),
        )
        # get_delta_table already re-raises known-transient object-store blips as
        # NonReportableError (see DeltaTableRef._capture_unless_transient) and
        # intentionally skips reporting them itself — don't undo that here.
        if not isinstance(e, NonReportableError):
            capture_exception(e)
        raise


def mark_batch_as_processed(
    team_id: int, schema_id: str, run_uuid: str, batch_index: int, destination_id: str | None = None
) -> None:
    """Mark a batch as processed at one destination."""
    with get_redis_client() as redis_client:
        if redis_client is None:
            logger.warning(
                "failed_to_mark_batch_processed",
                team_id=team_id,
                schema_id=schema_id,
                run_uuid=run_uuid,
                batch_index=batch_index,
            )
            return

        key = get_idempotency_key(team_id, schema_id, run_uuid, batch_index, destination_id)
        redis_client.set(key, "1", ex=IDEMPOTENCY_TTL_SECONDS)
