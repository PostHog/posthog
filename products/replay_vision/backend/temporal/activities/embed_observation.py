"""Side-effect: emit embedding requests for an observation's reasoning (or summarizer facets).

Fires `emit_embedding_request` calls so the text lands as rows in `document_embeddings`, scoped to the
scanner via `metadata.scanner_id` for later natural-language search. monitor/classifier/scorer embed their
`reasoning` paragraph under `rendering="reasoning"`; the summarizer embeds its facets (`intent`, `outcome`,
`friction_points`, `keywords`) under per-facet renderings. Empty content is skipped. Any failure surfaces to
the workflow and fails the observation.

The structured result (monitor `verdict`, scorer `score`, classifier `tags`) is stamped into `metadata` so
search can filter by exact outcome inside the same ClickHouse ranking query, with no second-pass lookup.
"""

from typing import Any
from uuid import UUID

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.kafka_client.client import ProduceResult
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC

from products.replay_vision.backend.tags import slugify_tag
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput
from products.replay_vision.backend.temporal.scanners.scorer import ScorerOutput
from products.replay_vision.backend.temporal.scanners.summarizer import SummarizerOutput
from products.replay_vision.backend.temporal.types import (
    AnyScannerOutput,
    EmbedObservationInputs,
    EmbedSummarizerObservationInputs,
)

logger = structlog.get_logger(__name__)

OBSERVATION_EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072
_PRODUCT = "replay-vision"
_DOCUMENT_TYPE = "replay-observation"
# Bounded so broker errors surface as activity failures instead of getting lost in the producer buffer.
_KAFKA_DELIVERY_TIMEOUT_S = 10.0


def _renderings_for(model_output: AnyScannerOutput) -> list[tuple[str, str]]:
    """Map a scanner output to `(rendering, content)` pairs to embed; the summarizer splits into facets,
    every other type embeds its single `reasoning` paragraph."""
    if isinstance(model_output, SummarizerOutput):
        return [
            ("intent", model_output.intent),
            ("outcome", model_output.outcome),
            ("friction_points", "\n".join(model_output.friction_points)),
            ("keywords", ", ".join(model_output.keywords)),
        ]
    # monitor / classifier / scorer all carry a free-text `reasoning` field.
    return [("reasoning", model_output.reasoning)]


def _result_metadata(model_output: AnyScannerOutput) -> dict[str, Any]:
    """The exact outcome to stamp into the embedding metadata so search can filter on it inside ClickHouse."""
    if isinstance(model_output, MonitorOutput):
        return {"verdict": model_output.verdict}
    if isinstance(model_output, ScorerOutput):
        return {"score": model_output.score}
    if isinstance(model_output, ClassifierOutput):
        # Slugify fixed-vocab tags too (freeform are already slug) so the stored side is canonical and search
        # filters match case/format-insensitively. Order-preserving dedup across both lists.
        tags = [*model_output.tags, *model_output.tags_freeform]
        return {"tags": list(dict.fromkeys(s for t in tags if (s := slugify_tag(t))))}
    return {}


async def _emit_embeddings(
    *, team_id: int, session_id: str, observation_id: UUID, metadata: dict[str, Any], renderings: list[tuple[str, str]]
) -> None:
    """Emit one embedding request per non-empty rendering and confirm broker delivery."""

    def emit_all() -> None:
        results: list[tuple[str, ProduceResult]] = []
        with producer_scope(topic=KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC, flush_timeout=_KAFKA_DELIVERY_TIMEOUT_S):
            for rendering, content in renderings:
                if not content.strip():
                    continue
                result = emit_embedding_request(
                    content=content,
                    team_id=team_id,
                    product=_PRODUCT,
                    document_type=_DOCUMENT_TYPE,
                    rendering=rendering,
                    document_id=str(observation_id),
                    models=[OBSERVATION_EMBEDDING_MODEL.value],
                    metadata=metadata,
                )
                results.append((rendering, result))
        for rendering, result in results:
            try:
                result.get(timeout=0)
            except Exception:
                logger.exception(
                    "replay_vision.embed_observation.kafka_delivery_failed",
                    session_id=session_id,
                    observation_id=str(observation_id),
                    rendering=rendering,
                )
                raise
            logger.debug(
                "replay_vision.embed_observation.rendering_emitted",
                session_id=session_id,
                observation_id=str(observation_id),
                rendering=rendering,
            )

    await sync_to_async(emit_all, thread_sensitive=False)()


@activity.defn
@track_activity()
async def embed_observation_activity(inputs: EmbedObservationInputs) -> None:
    """Emit one embedding per non-empty rendering of the observation's explanation text."""
    metadata = {
        "session_id": inputs.session_id,
        "team_id": inputs.team_id,
        "observation_id": str(inputs.observation_id),
        "scanner_id": str(inputs.scanner_id),
        **_result_metadata(inputs.model_output),
    }
    await _emit_embeddings(
        team_id=inputs.team_id,
        session_id=inputs.session_id,
        observation_id=inputs.observation_id,
        metadata=metadata,
        renderings=_renderings_for(inputs.model_output),
    )


# TODO: remove this back-compat alias after the deploy window (see REMOVAL CRITERION below).
@activity.defn
@track_activity()
async def embed_summarizer_observation_activity(inputs: EmbedSummarizerObservationInputs) -> None:
    """Back-compat alias under the pre-rename activity name, so summarizer workflows already in flight when the
    activity was renamed can still resolve their scheduled task. Mirrors the old behavior (facet embeddings,
    no `scanner_id`/result metadata).

    REMOVAL CRITERION: ApplyScannerWorkflow runs are short (≤1h execution timeout), so once a deploy shipping the
    rename has been live for >1h, no pre-rename run can still be in flight. A follow-up PR after that window
    should delete this alias and `EmbedSummarizerObservationInputs`, and drop it from the worker activity lists.
    """
    metadata = {
        "session_id": inputs.session_id,
        "team_id": inputs.team_id,
        "observation_id": str(inputs.observation_id),
    }
    await _emit_embeddings(
        team_id=inputs.team_id,
        session_id=inputs.session_id,
        observation_id=inputs.observation_id,
        metadata=metadata,
        renderings=_renderings_for(inputs.summarizer_output),
    )


__all__ = ["embed_observation_activity", "embed_summarizer_observation_activity"]
