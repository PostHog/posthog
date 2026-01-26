import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import structlog

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_AGENT_EVENTS

logger = structlog.get_logger(__name__)


@dataclass
class AgentLogEntry:
    team_id: int
    task_id: str
    run_id: str
    sequence: int
    timestamp: str
    entry_type: str
    entry: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        timestamp = datetime.utcnow().isoformat() + "Z"

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
