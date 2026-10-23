"""Side-effect: embed an observation's explanation text, and rank the observation for What to watch.

Stores the text through the embedding worker's synchronous endpoint, so it lands as a row in
`document_embeddings`, scoped to the scanner via `metadata.scanner_id` for later natural-language search. monitor/classifier/scorer embed their
`reasoning` paragraph under `rendering="reasoning"`; the summarizer embeds its title and summary as one
document under `rendering="summary"`. Empty content is skipped. Failures surface to the workflow, which
logs and swallows them — the observation is already marked succeeded.

The structured result (monitor `verdict`, scorer `score`, classifier `tags`) is stamped into `metadata` so
search can filter by exact outcome inside the same ClickHouse ranking query, with no second-pass lookup.

The endpoint also returns the vector, and the activity ranks the observation from it (see `watch_rank`).
"""

from typing import Any
from uuid import UUID

from django.utils import timezone

import httpx
import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.api.embedding_worker import async_generate_and_store_embedding

from products.replay_vision.backend.embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    OBSERVATION_EMBEDDING_MODEL,
)
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.observation_formatting import flatten_markdown
from products.replay_vision.backend.tags import slugify_tag
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.scanners.classifier import ClassifierOutput
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput
from products.replay_vision.backend.temporal.scanners.scorer import ScorerOutput
from products.replay_vision.backend.temporal.types import AnyScannerOutput, EmbedObservationInputs
from products.replay_vision.backend.watch_rank import (
    DUPLICATE_MAX_DISTANCE,
    WatchRank,
    anchor_vectors,
    classify,
    duplicate_root,
    nearest_earlier_observation,
)

logger = structlog.get_logger(__name__)


def _renderings_for(model_output: AnyScannerOutput) -> list[tuple[str, str]]:
    """The `(rendering, content)` pairs to embed for one scanner output, or none when it has nothing to say.

    Flattened first: markdown syntax the model wrote is not meaning, and embedding `**` and `##` tokens
    dilutes the vector that semantic search ranks on.
    """
    document = model_output.embedding_document()
    return [(document.rendering, flatten_markdown(document.text))] if document else []


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


async def _rank(*, team_id: int, scanner_id: UUID, observation_id: UUID, vector: list[float]) -> None:
    category, contrast = classify(vector, await anchor_vectors(team_id))
    nearest = await sync_to_async(nearest_earlier_observation, thread_sensitive=False)(
        team_id=team_id,
        scanner_id=str(scanner_id),
        observation_id=str(observation_id),
        vector=vector,
        now=timezone.now(),
    )
    duplicate_of: str | None = None
    if nearest is not None and nearest[1] <= DUPLICATE_MAX_DISTANCE:
        neighbour_rank = await (
            ReplayObservation.objects.filter(team_id=team_id, id=nearest[0])
            .values_list("watch_rank", flat=True)
            .afirst()
        )
        duplicate_of = duplicate_root(nearest[0], neighbour_rank)
    rank = WatchRank(category=category, contrast=contrast, duplicate_of=duplicate_of)
    await ReplayObservation.objects.filter(team_id=team_id, id=observation_id).aupdate(watch_rank=rank.to_json())


async def _store_and_rank(
    *, team_id: int, scanner_id: UUID, observation_id: UUID, metadata: dict[str, Any], renderings: list[tuple[str, str]]
) -> None:
    """Store each rendering through the synchronous endpoint, then rank the observation from the first vector."""
    vector: list[float] | None = None
    for rendering, content in renderings:
        if not content.strip():
            continue
        try:
            vectors = await async_generate_and_store_embedding(
                content,
                team_id=team_id,
                product=EMBEDDING_PRODUCT,
                document_type=EMBEDDING_DOCUMENT_TYPE,
                rendering=rendering,
                document_id=str(observation_id),
                models=[OBSERVATION_EMBEDDING_MODEL.value],
                metadata=metadata,
            )
        except httpx.HTTPStatusError as e:
            # The worker refuses an organization without AI data processing, so a retry cannot succeed.
            if e.response.status_code == 403:
                return
            raise
        vector = vector or vectors.get(OBSERVATION_EMBEDDING_MODEL.value)
    if vector is None:
        return
    # The embedding is stored by now, so a ranking failure must not fail the activity: a retry
    # would embed and store the text again.
    try:
        await _rank(team_id=team_id, scanner_id=scanner_id, observation_id=observation_id, vector=vector)
    except Exception:
        logger.exception("replay_vision.embed_observation.rank_failed", observation_id=str(observation_id))


@activity.defn
@track_activity(side_effect="embed")
async def embed_observation_activity(inputs: EmbedObservationInputs) -> None:
    """Embed the observation's explanation text when it is non-empty, and rank the observation."""
    metadata = {
        "session_id": inputs.session_id,
        "team_id": inputs.team_id,
        "observation_id": str(inputs.observation_id),
        "scanner_id": str(inputs.scanner_id),
        **_result_metadata(inputs.model_output),
    }
    await _store_and_rank(
        team_id=inputs.team_id,
        scanner_id=inputs.scanner_id,
        observation_id=inputs.observation_id,
        metadata=metadata,
        renderings=_renderings_for(inputs.model_output),
    )


__all__ = ["embed_observation_activity"]
