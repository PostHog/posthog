"""Side-effect: emit per-facet embedding requests for an indexer observation.

Fires four `emit_embedding_request` calls — one each for `intent`, `outcome`, `friction_points`, `keywords` —
under different `rendering` values so they coexist as separate rows in `document_embeddings`. Empty facets
(e.g. no friction_points) are skipped. Any failure surfaces to the workflow and fails the observation.
"""

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request

from products.replay_vision.backend.temporal.types import EmbedIndexerObservationInputs

logger = structlog.get_logger(__name__)

INDEXER_EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
_PRODUCT = "replay-vision"
_DOCUMENT_TYPE = "replay-observation"
# Bounded so broker errors surface as activity failures instead of getting lost in the producer buffer.
_KAFKA_DELIVERY_TIMEOUT_S = 10.0


@activity.defn
async def embed_indexer_observation_activity(inputs: EmbedIndexerObservationInputs) -> None:
    """One embedding per non-empty indexer facet (intent / outcome / friction_points / keywords)."""
    out = inputs.indexer_output
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

    for rendering, content in facets:
        if not content.strip():
            continue
        result = await sync_to_async(emit_embedding_request, thread_sensitive=False)(
            content=content,
            team_id=inputs.team_id,
            product=_PRODUCT,
            document_type=_DOCUMENT_TYPE,
            rendering=rendering,
            document_id=str(inputs.observation_id),
            models=[INDEXER_EMBEDDING_MODEL.value],
            metadata=metadata,
        )
        # Block on the delivery callback so broker errors propagate; `.get()` raises KafkaException on failure.
        await sync_to_async(result.get, thread_sensitive=False)(timeout=_KAFKA_DELIVERY_TIMEOUT_S)
        logger.debug(
            "replay_vision.embed_indexer.facet_emitted",
            session_id=inputs.session_id,
            observation_id=str(inputs.observation_id),
            rendering=rendering,
        )


__all__ = ["embed_indexer_observation_activity"]
