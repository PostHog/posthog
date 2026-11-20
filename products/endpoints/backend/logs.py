import json
import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Optional

import structlog

from posthog.dataclasses import frozen
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_LOG_ENTRIES

from products.endpoints.backend.constants import ENDPOINT_EXECUTION_RECORDS_LOG_SOURCE, ENDPOINTS_LOG_SOURCE

if TYPE_CHECKING:
    from products.endpoints.backend.logic.execution import ExecutionType

logger = structlog.get_logger(__name__)

CacheOutcome = Literal["hit", "miss"]
ExecutionStatus = Literal["success", "user_error", "query_performance", "capacity", "error"]


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


@frozen
class EndpointExecutionRecord:
    """What one endpoint run did and how the caller asked for it, as data instead of prose.

    Usage analysis reads these fields, so a renamed or removed field breaks its readers. Only
    non-sensitive execution metadata belongs here. Never add variable values, for the reason
    `build_execution_message` gives.
    """

    execution_type: "ExecutionType"
    status: ExecutionStatus
    version: int
    duration_ms: int
    cache_outcome: CacheOutcome | None = None
    rows: int | None = None
    error: str | None = None
    access_method: str | None = None
    is_interactive: bool = False
    has_variables: bool = False
    has_filters_override: bool = False
    has_limit: bool = False
    has_offset: bool = False
    refresh_mode: str | None = None

    def to_message(self) -> str:
        fields = {key: value for key, value in dataclasses.asdict(self).items() if value is not None}
        return json.dumps(fields, separators=(",", ":"))


def log_endpoint_execution(
    *,
    team_id: int,
    endpoint_id: str,
    instance_id: str,
    level: str,
    message: str,
) -> None:
    """Emit a user-facing endpoint execution log entry to the `log_entries` table."""
    _produce_log_entry(
        team_id=team_id,
        log_source=ENDPOINTS_LOG_SOURCE,
        endpoint_id=endpoint_id,
        instance_id=instance_id,
        level=level,
        message=message,
    )


def log_endpoint_execution_record(
    *,
    team_id: int,
    endpoint_id: str,
    instance_id: str,
    record: EndpointExecutionRecord,
) -> None:
    """Emit the record of one endpoint run to the `log_entries` table, under a source no viewer reads."""
    _produce_log_entry(
        team_id=team_id,
        log_source=ENDPOINT_EXECUTION_RECORDS_LOG_SOURCE,
        endpoint_id=endpoint_id,
        instance_id=instance_id,
        level="INFO" if record.status == "success" else "ERROR",
        message=record.to_message(),
    )


def _produce_log_entry(
    *,
    team_id: int,
    log_source: str,
    endpoint_id: str,
    instance_id: str,
    level: str,
    message: str,
) -> None:
    """Best-effort: a produce failure must never break or slow down an endpoint run, so failures are
    swallowed (debug-logged). We don't flush — `produce()` polls non-blocking.
    """
    try:
        producer = get_producer(topic=KAFKA_LOG_ENTRIES)
        producer.produce(
            topic=KAFKA_LOG_ENTRIES,
            data={
                "team_id": team_id,
                "log_source": log_source,
                "log_source_id": str(endpoint_id),
                "instance_id": instance_id,
                "timestamp": datetime.now(tz=UTC).strftime(_TIMESTAMP_FORMAT),
                "level": level,
                "message": message,
            },
        )
    except Exception:
        logger.debug("Failed to emit endpoint execution log entry", exc_info=True)
