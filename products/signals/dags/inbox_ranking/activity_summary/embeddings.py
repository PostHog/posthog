"""The embedding round trip behind `activity_summary_embeddings`.

Each summary goes through the embedding worker, the path the report embeddings take, so a summary
vector shares its model and space with the report vectors. The worker writes to
`document_embeddings` asynchronously, so the asset emits, waits, and reads back what landed.
"""

import datetime
from collections.abc import Collection
from typing import Any, cast

from posthog.api.embedding_worker import emit_embedding_request
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.dataclasses import frozen
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC
from posthog.schema_enums import EmbeddingModelName

from products.signals.backend.report_embeddings import EMBEDDING_PRODUCT
from products.signals.dags.inbox_ranking.dataset.queries import EMBEDDINGS_TABLE, etl_workload

EMBEDDING_DOCUMENT_TYPE = "activity_summary"
EMBEDDING_RENDERING = "summary_text"
# The model `EMBEDDINGS_TABLE` holds. The worker also writes the other models, like the report rows.
EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536
KAFKA_FLUSH_TIMEOUT_SECONDS = 60.0

# `timestamp` is in the table's sort key as `toDate(timestamp)`, and every row of a partition carries
# the partition day, so the day bound prunes the read to one day of the table.
SUMMARY_EMBEDDINGS_SQL = f"""
SELECT
    team_id,
    document_id,
    argMax(embedding, inserted_at) AS embedding,
    argMax(content, inserted_at) AS content
FROM {EMBEDDINGS_TABLE}
WHERE product = %(product)s
  AND document_type = %(document_type)s
  AND rendering = %(rendering)s
  AND team_id IN %(team_ids)s
  AND document_id IN %(document_ids)s
  AND timestamp >= %(day_start)s
  AND timestamp < %(day_end)s
GROUP BY team_id, document_id
"""
SUMMARY_EMBEDDINGS_QUERY_SETTINGS: dict[str, int] = {"max_execution_time": 120}


@frozen(order=True)
class SummaryDocument:
    team_id: int
    document_id: str


@frozen
class LandedVector:
    embedding: list[float]
    content: str


def document_id(user_id: int, partition_key: str) -> str:
    """One document per (user, partition). The team is part of the table's key on its own."""
    return f"{user_id}:{partition_key}"


def emit_summary_embedding(
    *, team_id: int, user_id: int, partition_key: str, prompt_version: int, text: str, day_start: datetime.datetime
) -> None:
    """Queue one summary for the worker.

    `timestamp` is the partition day, not the emission time: the table replaces on a key that holds
    `toDate(timestamp)`, so a re-run supersedes its own row instead of adding a second one."""
    emit_embedding_request(
        content=text,
        team_id=team_id,
        product=EMBEDDING_PRODUCT,
        document_type=EMBEDDING_DOCUMENT_TYPE,
        rendering=EMBEDDING_RENDERING,
        document_id=document_id(user_id, partition_key),
        models=[model.value for model in EmbeddingModelName],
        timestamp=day_start,
        metadata={
            "team_id": team_id,
            "user_id": user_id,
            "partition": partition_key,
            "prompt_version": prompt_version,
        },
    )


def flush_embedding_requests() -> None:
    """Deliver every queued request before the asset waits for the vectors, so a broken producer
    fails the run instead of looking like a slow worker."""
    undelivered = get_producer(topic=KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC).flush(KAFKA_FLUSH_TIMEOUT_SECONDS)
    if undelivered:
        raise RuntimeError(f"{undelivered} embedding requests were not delivered to Kafka")


def landed_vectors(
    documents: Collection[SummaryDocument], day_start: datetime.datetime
) -> dict[SummaryDocument, LandedVector]:
    """The latest vector and the text it embeds for each document that has one."""
    if not documents:
        return {}
    rows = cast(
        list[tuple[Any, ...]],
        sync_execute(
            SUMMARY_EMBEDDINGS_SQL,
            {
                "product": EMBEDDING_PRODUCT,
                "document_type": EMBEDDING_DOCUMENT_TYPE,
                "rendering": EMBEDDING_RENDERING,
                "team_ids": sorted({document.team_id for document in documents}),
                "document_ids": sorted({document.document_id for document in documents}),
                "day_start": day_start.replace(tzinfo=None),
                "day_end": (day_start + datetime.timedelta(days=1)).replace(tzinfo=None),
            },
            settings=SUMMARY_EMBEDDINGS_QUERY_SETTINGS,
            workload=etl_workload(),
            ch_user=ClickHouseUser.SIGNALS,
        )
        or [],
    )
    return {
        SummaryDocument(team_id=int(team_id), document_id=str(doc_id)): LandedVector(
            embedding=list(embedding), content=str(content)
        )
        for team_id, doc_id, embedding, content in rows
    }


def pending_documents(
    wanted: dict[SummaryDocument, str], landed: dict[SummaryDocument, LandedVector]
) -> list[SummaryDocument]:
    """The documents with no vector yet, or with a vector of other text, such as one written before
    the summaries partition was re-run."""
    return sorted(
        document
        for document, text in wanted.items()
        if (vector := landed.get(document)) is None or vector.content != text
    )
