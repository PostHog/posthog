import json
import re
from datetime import datetime
from typing import Any

import structlog
from pydantic import BaseModel, field_validator

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_AGENT_EVENTS

logger = structlog.get_logger(__name__)

# ClickHouse DateTime64 format: YYYY-MM-DD HH:MM:SS.mmm
CLICKHOUSE_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_timestamp_for_clickhouse(dt: datetime) -> str:
    """Format datetime for ClickHouse DateTime64(3, 'UTC')."""
    return dt.strftime(CLICKHOUSE_DATETIME_FORMAT) + f".{dt.microsecond // 1000:03d}"


def normalize_timestamp(timestamp: str) -> str:
    """
    Convert various timestamp formats to ClickHouse DateTime64 format.
    Handles ISO 8601 format (with T and Z) and already-correct format.
    """
    # Already in correct format: YYYY-MM-DD HH:MM:SS.mmm
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$", timestamp):
        return timestamp

    # ISO 8601 with T separator and optional Z suffix: 2026-01-27T15:23:30.773Z
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z?$", timestamp)
    if iso_match:
        date_part = iso_match.group(1)
        time_part = iso_match.group(2)
        ms_part = iso_match.group(3) or "000"
        # Truncate or pad milliseconds to 3 digits
        ms_part = ms_part[:3].ljust(3, "0")
        return f"{date_part} {time_part}.{ms_part}"

    # Fallback: try to parse and reformat
    try:
        # Try parsing as ISO format
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return format_timestamp_for_clickhouse(dt)
    except ValueError:
        logger.warning("Could not parse timestamp, using current time", original_timestamp=timestamp)
        return format_timestamp_for_clickhouse(datetime.utcnow())


class AgentLogEntry(BaseModel):
    team_id: int
    task_id: str
    run_id: str
    sequence: int
    timestamp: str
    entry_type: str
    entry: str

    @field_validator("timestamp")
    @classmethod
    def validate_and_normalize_timestamp(cls, v: str) -> str:
        return normalize_timestamp(v)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def create_agent_log_entry(
    team_id: int,
    task_id: str,
    run_id: str,
    sequence: int,
    entry_type: str,
    entry: dict[str, Any],
    timestamp: str | None = None,
) -> AgentLogEntry:
    if timestamp is None:
        timestamp = format_timestamp_for_clickhouse(datetime.utcnow())

    return AgentLogEntry(
        team_id=team_id,
        task_id=task_id,
        run_id=run_id,
        sequence=sequence,
        timestamp=timestamp,
        entry_type=entry_type,
        entry=json.dumps(entry),
    )


def produce_agent_log_entry(entry: AgentLogEntry) -> None:
    try:
        producer = KafkaProducer()
        future = producer.produce(
            topic=KAFKA_AGENT_EVENTS,
            data=entry.to_dict(),
            key=f"{entry.task_id}:{entry.run_id}",
        )
        future.get()
    except Exception as e:
        logger.exception(
            "Failed to produce agent log entry",
            task_id=entry.task_id,
            run_id=entry.run_id,
            sequence=entry.sequence,
            error=e,
        )
        raise


def produce_agent_log_entries(entries: list[AgentLogEntry]) -> None:
    if not entries:
        return

    try:
        producer = KafkaProducer()
        futures = []
        for entry in entries:
            future = producer.produce(
                topic=KAFKA_AGENT_EVENTS,
                data=entry.to_dict(),
                key=f"{entry.task_id}:{entry.run_id}",
            )
            futures.append(future)

        for future in futures:
            future.get()
    except Exception as e:
        logger.exception(
            "Failed to produce agent log entries",
            count=len(entries),
            error=e,
        )
        raise
