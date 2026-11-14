"""Store intent vectors only after inference returns, without queued embedding output."""

import json
import math
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.utils import timezone

from posthog.schema import HogQLQueryModifiers

from posthog.api.embedding_worker import generate_embedding
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.models.event.new_events_schema import events_route_scope
from posthog.models.team.team import Team

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.mcp_analytics.backend.facade.contracts import IntentGenerationUnavailable
from products.mcp_analytics.backend.intent_topics.constants import (
    EMBEDDING_DIMENSION,
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_MODEL,
    EMBEDDING_PRODUCT,
    EMBEDDING_RENDERING,
    MAX_EMBEDDING_TEXT_LENGTH,
)
from products.mcp_analytics.backend.intent_topics.corpus import DistinctIntent


def select_intents_to_emit(intents: Iterable[DistinctIntent], seen: set[str]) -> list[DistinctIntent]:
    return [intent for intent in intents if intent.hash not in seen]


def ensure_embedding_allowed(team: Team) -> None:
    """Intent text is user-authored, so embedding it needs the organization's AI data processing consent."""
    if not team.organization.is_ai_data_processing_approved:
        raise IntentGenerationUnavailable("AI data processing is not approved for this organization")


EMBEDDING_BATCH_SIZE = 32
EMBEDDING_CONCURRENCY = 8
EMBEDDING_TIMEOUT_SECONDS = 30.0
_EMBEDDING_TABLE = next(t for t in EMBEDDING_TABLES if t.model_name == EMBEDDING_MODEL).distributed_table_name()


def write_intent_embeddings(team: Team, intents: Sequence[DistinctIntent]) -> int:
    if not intents:
        return 0
    if len(intents) > EMBEDDING_BATCH_SIZE:
        raise ValueError("Intent embedding batch exceeds its bound")
    ensure_embedding_allowed(team)

    def generate(intent: DistinctIntent) -> list[float]:
        result = generate_embedding(
            team,
            intent.text[:MAX_EMBEDDING_TEXT_LENGTH],
            model=EMBEDDING_MODEL,
            no_truncate=True,
            timeout=EMBEDDING_TIMEOUT_SECONDS,
        )
        if len(result.embedding) != EMBEDDING_DIMENSION or not all(math.isfinite(v) for v in result.embedding):
            raise ValueError("Invalid intent embedding vector")
        return result.embedding

    # Only this thread writes. Even an inference failure joins all requests before the run can finish.
    with ThreadPoolExecutor(max_workers=EMBEDDING_CONCURRENCY) as executor:
        vectors = list(executor.map(generate, intents))
    inserted_at = timezone.now()
    with events_route_scope(HogQLQueryModifiers(useNewEventsSchema=False)):
        sync_execute(
            f"""INSERT INTO {_EMBEDDING_TABLE}
            (team_id, product, document_type, rendering, document_id, timestamp, inserted_at, content, metadata, embedding)
            VALUES""",
            [
                (
                    team.pk,
                    EMBEDDING_PRODUCT,
                    EMBEDDING_DOCUMENT_TYPE,
                    EMBEDDING_RENDERING,
                    intent.hash,
                    intent.source_min_timestamp,
                    inserted_at,
                    intent.text[:MAX_EMBEDDING_TEXT_LENGTH],
                    json.dumps(
                        {"calls": intent.calls, "source_min_timestamp": intent.source_min_timestamp.isoformat()}
                    ),
                    vector,
                )
                for intent, vector in zip(intents, vectors, strict=True)
            ],
            team_id=team.pk,
            workload=Workload.OFFLINE,
            settings={
                "insert_distributed_sync": 1,
                "async_insert": 0,
                "insert_quorum": 0 if settings.TEST or settings.DEBUG else "auto",
                "insert_quorum_timeout": 60_000,
            },
            send_receive_timeout=90,
        )
    return len(intents)
