from datetime import UTC, datetime
from typing import Optional

import structlog

from posthog.dataclasses import frozen
from posthog.internal_logs import send_internal_log
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES

from products.endpoints.backend.constants import ENDPOINTS_LOG_SOURCE

logger = structlog.get_logger(__name__)


# ClickHouse DateTime64(6, 'UTC') input format — same as the temporal logger uses.
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


@frozen
class RunRequestShape:
    """How the caller asked for a run. It holds the number of variables, never their values."""

    refresh: Optional[str] = None
    access: Optional[str] = None
    variables: int = 0
    filters_override: bool = False
    limit: Optional[int] = None
    offset: Optional[int] = None


def build_execution_message(
    *,
    succeeded: bool,
    execution_type: str,
    cache_outcome: Optional[str] = None,
    duration_ms: Optional[int] = None,
    rows: Optional[int] = None,
    version: Optional[int] = None,
    error: Optional[str] = None,
    request: Optional[RunRequestShape] = None,
) -> str:
    """One human-readable line carrying the extra data as searchable `key=value` tokens.

    Only non-sensitive execution metadata belongs here. Never add variable values — they
    routinely carry PII (emails, customer IDs, filter values) and must stay out of logs.
    """
    prefix = "Endpoint executed" if succeeded else "Endpoint execution failed"
    tokens = {
        "path": execution_type,
        "cache": cache_outcome,
        "duration_ms": duration_ms,
        "rows": rows,
        "version": version,
        "error": error,
    }
    if request is not None:
        tokens.update(
            {
                "refresh": request.refresh,
                "access": request.access,
                "variables": request.variables or None,
                "filters_override": "true" if request.filters_override else None,
                "limit": request.limit,
                "offset": request.offset,
            }
        )
    token_str = " ".join(f"{key}={value}" for key, value in tokens.items() if value is not None)
    return f"{prefix} · {token_str}" if token_str else prefix


def log_endpoint_execution(
    *,
    team_id: int,
    endpoint_id: str,
    instance_id: str,
    level: str,
    message: str,
) -> None:
    """Emit a user-facing endpoint execution log entry to `log_entries` (via Kafka) and to the logs product.

    Best-effort: a failed write must never break or slow down an endpoint run, so each write swallows
    its own failure (debug-logged) and does not stop the other. We don't flush — `produce()` polls
    non-blocking.
    """
    now = datetime.now(tz=UTC)
    try:
        producer = get_producer(topic=KAFKA_LOG_ENTRIES)
        producer.produce(
            topic=KAFKA_LOG_ENTRIES,
            data={
                "team_id": team_id,
                "log_source": ENDPOINTS_LOG_SOURCE,
                "log_source_id": str(endpoint_id),
                "instance_id": instance_id,
                "timestamp": now.strftime(_TIMESTAMP_FORMAT),
                "level": level,
                "message": message,
            },
        )
    except Exception:
        logger.debug("Failed to emit endpoint execution log entry", exc_info=True)
    try:
        send_internal_log(
            ENDPOINTS_LOG_SOURCE,
            team_id=team_id,
            log_source_id=str(endpoint_id),
            instance_id=instance_id,
            timestamp=now,
            level=level,
            message=message,
        )
    except Exception:
        logger.debug("Failed to send endpoint execution log entry to the logs product", exc_info=True)
