from datetime import UTC, datetime
from typing import Optional

import structlog

from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES

logger = structlog.get_logger(__name__)

# Matches the `log_source` column written for endpoint execution logs in the `log_entries`
# ClickHouse table. The Logs tab and the `endpoints_logs_retrieve` API both read by this value.
ENDPOINTS_LOG_SOURCE = "endpoints"

# ClickHouse DateTime64(6, 'UTC') input format — same as the temporal logger uses.
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def build_execution_message(
    *,
    succeeded: bool,
    execution_type: str,
    cache_outcome: Optional[str] = None,
    duration_ms: Optional[int] = None,
    rows: Optional[int] = None,
    version: Optional[int] = None,
    error: Optional[str] = None,
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
    """Emit a user-facing endpoint execution log entry to the `log_entries` table.

    Best-effort: a produce failure must never break or slow down an endpoint run, so failures are
    swallowed (debug-logged). We don't flush — `produce()` polls non-blocking.
    """
    try:
        producer = get_producer(topic=KAFKA_LOG_ENTRIES)
        producer.produce(
            topic=KAFKA_LOG_ENTRIES,
            data={
                "team_id": team_id,
                "log_source": ENDPOINTS_LOG_SOURCE,
                "log_source_id": str(endpoint_id),
                "instance_id": instance_id,
                "timestamp": datetime.now(tz=UTC).strftime(_TIMESTAMP_FORMAT),
                "level": level,
                "message": message,
            },
        )
    except Exception:
        logger.debug("Failed to emit endpoint execution log entry", exc_info=True)
