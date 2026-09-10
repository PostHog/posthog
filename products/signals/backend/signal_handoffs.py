from __future__ import annotations

import json
from dataclasses import asdict, field, replace
from datetime import datetime
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async

from posthog.api.embedding_worker import emit_embedding_request
from posthog.dataclasses import frozen
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC
from posthog.schema_enums import EmbeddingModelName
from posthog.storage import object_storage

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.signal_costs import CostStage, add_cost, merge_costs

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData
    from products.tasks.backend.facade.contracts import TaskRunSpend


@frozen
class SignalHandoff:
    team_id: int
    signal: SignalData
    embedding: list[float]
    published: bool = False
    costed_tasks: list[str] = field(default_factory=list)


def signal_key(team_id: int, signal_id: str) -> str:
    return f"signals/processing/{team_id}/{signal_id}.json"


async def write_handoff(handoff: SignalHandoff) -> str:
    payload = asdict(handoff)
    payload["signal"]["timestamp"] = handoff.signal.timestamp.isoformat()
    payload["signal"]["inserted_at"] = (
        handoff.signal.inserted_at.isoformat() if handoff.signal.inserted_at is not None else None
    )
    key = signal_key(handoff.team_id, handoff.signal.signal_id)
    await sync_to_async(object_storage.write, thread_sensitive=False)(key, json.dumps(payload))
    return key


async def read_handoff(key: str, team_id: int) -> SignalHandoff:
    # The temporal package imports this module while registering its activities.
    from products.signals.backend.temporal.types import SignalData  # noqa: PLC0415

    if not key.startswith(f"signals/processing/{team_id}/"):
        raise ValueError("Signal handoff belongs to another team")
    content = await sync_to_async(object_storage.read, thread_sensitive=False)(key)
    if content is None:
        raise ValueError("Signal handoff is missing")
    payload = json.loads(content)
    if payload["team_id"] != team_id:
        raise ValueError("Signal handoff belongs to another team")
    signal = payload["signal"]
    signal["timestamp"] = datetime.fromisoformat(signal["timestamp"])
    if signal.get("inserted_at") is not None:
        signal["inserted_at"] = datetime.fromisoformat(signal["inserted_at"])
    return SignalHandoff(
        team_id=team_id,
        signal=SignalData(**signal),
        embedding=payload["embedding"],
        published=payload.get("published", False),
        costed_tasks=payload.get("costed_tasks", []),
    )


def add_task_cost(handoff: SignalHandoff, task_id: str, spend: TaskRunSpend, stage: CostStage) -> None:
    if task_id not in handoff.costed_tasks:
        add_cost(handoff.signal.metadata, "task", spend.token_cost, spend.compute_cost, stage)
        handoff.costed_tasks.append(task_id)


async def publish_signal(handoff: SignalHandoff) -> None:
    signal = handoff.signal
    merge_costs(signal.metadata, {})
    report_status = (
        await SignalReport.objects.filter(team_id=handoff.team_id, id=signal.metadata["report_id"])
        .values_list("status", flat=True)
        .afirst()
    )
    safety_judgment = (
        await SignalReportArtefact.objects.filter(
            team_id=handoff.team_id,
            report_id=signal.metadata["report_id"],
            type=SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
        )
        .order_by("-created_at")
        .values_list("content", flat=True)
        .afirst()
    )
    unsafe = safety_judgment is not None and json.loads(safety_judgment).get("choice") is False
    if report_status is None or report_status == SignalReport.Status.DELETED or unsafe:
        signal.metadata["deleted"] = True

    def emit() -> None:
        # The embedding worker populates the recently-seen store used by publication confirmation.
        with producer_scope(topic=KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC, flush_timeout=10):
            result = emit_embedding_request(
                content=signal.content,
                team_id=handoff.team_id,
                product="signals",
                document_type="signal",
                rendering="plain",
                document_id=signal.signal_id,
                models=[model.value for model in EmbeddingModelName],
                timestamp=signal.timestamp,
                metadata=signal.metadata,
            )
        result.get(timeout=1)

    await sync_to_async(emit, thread_sensitive=False)()


async def publish_handoff(key: str, team_id: int) -> None:
    handoff = await read_handoff(key, team_id)
    if not handoff.published:
        await publish_signal(handoff)
        await write_handoff(replace(handoff, published=True))
