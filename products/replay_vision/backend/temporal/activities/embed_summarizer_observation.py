"""Side-effect: emit per-facet embedding requests for a summarizer observation.

Fires `emit_embedding_request` calls — one each for `intent`, `outcome`, `friction_points`, `keywords` —
under different `rendering` values so they coexist as separate rows in `document_embeddings`. Empty facets
(e.g. no friction_points) are skipped. Any failure surfaces to the workflow and fails the observation.
"""

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.kafka_client.client import ProduceResult
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC

from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.types import EmbedSummarizerObservationInputs

logger = structlog.get_logger(__name__)

SUMMARIZER_EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
_PRODUCT = "replay-vision"
_DOCUMENT_TYPE = "replay-observation"
# Bounded so broker errors surface as activity failures instead of getting lost in the producer buffer.
_KAFKA_DELIVERY_TIMEOUT_S = 10.0


@activity.defn
@track_activity()
async def embed_summarizer_observation_activity(inputs: EmbedSummarizerObservationInputs) -> None:
    """One embedding per non-empty summarizer facet (intent / outcome / friction_points / keywords)."""
    out = inputs.summarizer_output
    facets: list[tuple[str, str]] = [
        ("intent", out.intent),
        ("outcome", out.outcome),
        ("friction_points", "\n".join(out.friction_points)),
        ("keywords", ", ".join(out.keywords)),
    ]
    metadata = {
        "session_id": inputs.session_id,
        "team_id": inputs.team_id,
        "observation_id": str(inputs.observation_id),
    }

    def emit_all() -> None:
        results: list[tuple[str, ProduceResult]] = []
        with producer_scope(topic=KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC, flush_timeout=_KAFKA_DELIVERY_TIMEOUT_S):
            for rendering, content in facets:
                if not content.strip():
                    continue
                result = emit_embedding_request(
                    content=content,
                    team_id=inputs.team_id,
                    product=_PRODUCT,
                    document_type=_DOCUMENT_TYPE,
                    rendering=rendering,
                    document_id=str(inputs.observation_id),
                    models=[SUMMARIZER_EMBEDDING_MODEL.value],
                    metadata=metadata,
                )
                results.append((rendering, result))
        for rendering, result in results:
            result.get(timeout=0)
            logger.debug(
                "replay_vision.embed_summarizer.facet_emitted",
                session_id=inputs.session_id,
                observation_id=str(inputs.observation_id),
                rendering=rendering,
            )

    await sync_to_async(emit_all, thread_sensitive=False)()


__all__ = ["embed_summarizer_observation_activity"]
