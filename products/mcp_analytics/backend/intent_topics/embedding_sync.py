"""Send intent texts to the embedding worker, once per distinct text per retention window."""

from collections.abc import Iterable, Sequence
from datetime import datetime

from posthog.api.embedding_worker import emit_embedding_request
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC
from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.contracts import IntentGenerationUnavailable
from products.mcp_analytics.backend.intent_topics.constants import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    EMBEDDING_PRODUCT,
    EMBEDDING_RENDERING,
)
from products.mcp_analytics.backend.intent_topics.corpus import DistinctIntent


def select_intents_to_emit(intents: Iterable[DistinctIntent], seen: set[str]) -> list[DistinctIntent]:
    return [intent for intent in intents if intent.hash not in seen]


def ensure_embedding_allowed(team: Team) -> None:
    """Intent text is user-authored, so embedding it needs the organization's AI data processing consent."""
    if not team.organization.is_ai_data_processing_approved:
        raise IntentGenerationUnavailable("AI data processing is not approved for this organization")


DELIVERY_BATCH_SIZE = 5_000
DELIVERY_TIMEOUT_SECONDS = 30.0


def emit_intent_embeddings(team: Team, intents: Sequence[DistinctIntent], *, now: datetime) -> int:
    """Emit one embedding request per intent and wait for Kafka to acknowledge each batch.

    A delivery failure raises, so the run fails and its retry emits the same intents again; an
    unconfirmed run would otherwise age the window out and lose them.
    """
    if not intents:
        return 0
    ensure_embedding_allowed(team)
    producer = get_producer(topic=KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC)
    for start in range(0, len(intents), DELIVERY_BATCH_SIZE):
        results = [
            emit_embedding_request(
                content=intent.text,
                team_id=team.pk,
                product=EMBEDDING_PRODUCT,
                document_type=EMBEDDING_DOCUMENT_TYPE,
                rendering=EMBEDDING_RENDERING,
                document_id=intent.hash,
                models=[EMBEDDING_MODEL],
                timestamp=now,
                metadata={"calls": intent.calls},
            )
            for intent in intents[start : start + DELIVERY_BATCH_SIZE]
        ]
        producer.flush(DELIVERY_TIMEOUT_SECONDS)
        for result in results:
            result.get(timeout=DELIVERY_TIMEOUT_SECONDS)
    return len(intents)
