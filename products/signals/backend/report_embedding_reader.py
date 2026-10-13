"""Reads the current vector of each report, for the ranking scorer.

`report_embeddings.py` writes one `document_embeddings` row per rendering of a report. The dataset
dag snapshots every report's latest row fleet-wide with `REPORT_EMBEDDINGS_SQL`. The scorer needs
the same latest row for a few reports of one team, so this read is that query with the team and
the report ids added. The team id is the table's sort-key prefix, so the read is a point read and
not a full scan.
"""

import datetime
from collections.abc import Sequence
from typing import Any, cast

from django.conf import settings

import numpy as np

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.report_embeddings import EMBEDDING_DOCUMENT_TYPE, EMBEDDING_PRODUCT

# The text-embedding-3-small-1536 table, which is the model the report documents are embedded with.
REPORT_EMBEDDINGS_TABLE = "distributed_posthog_document_embeddings_text_embedding_3_small_1536"

LATEST_REPORT_VECTORS_SQL = f"""
SELECT
    document_id,
    argMax(embedding, inserted_at) AS embedding,
    argMax(JSONExtractBool(metadata, 'deleted'), inserted_at) AS is_tombstone,
    max(inserted_at) AS embedding_inserted_at
FROM {REPORT_EMBEDDINGS_TABLE}
WHERE team_id = %(team_id)s
  AND product = %(product)s
  AND document_type = %(document_type)s
  AND rendering = %(rendering)s
  AND document_id IN %(report_ids)s
GROUP BY document_id
"""


@frozen
class ReportVector:
    # float32, EMBEDDING_DIMENSIONS wide.
    embedding: np.ndarray
    inserted_at: datetime.datetime


def latest_report_vectors(team_id: int, report_ids: Sequence[str], *, rendering: str) -> dict[str, ReportVector]:
    """The newest vector of each report in `rendering`, keyed by report id.

    A report whose newest row is a tombstone is absent, and so is a report with no row. An older
    live row never stands in for a tombstone, because the aggregate takes the newest row only. A
    vector of another width is from another model, so it is absent too. One query per batch of
    `INBOX_RANKING_SCORING_BATCH_SIZE` ids.
    """
    ids = list(dict.fromkeys(str(report_id) for report_id in report_ids))
    batch_size = settings.INBOX_RANKING_SCORING_BATCH_SIZE
    vectors: dict[str, ReportVector] = {}
    for start in range(0, len(ids), batch_size):
        tag_queries(
            product=Product.SIGNALS,
            feature=Feature.ENRICHMENT,
            team_id=team_id,
            query_type="inbox_ranking_report_vectors",
        )
        rows = cast(
            list[tuple[Any, ...]],
            sync_execute(
                LATEST_REPORT_VECTORS_SQL,
                {
                    "team_id": team_id,
                    "product": EMBEDDING_PRODUCT,
                    "document_type": EMBEDDING_DOCUMENT_TYPE,
                    "rendering": rendering,
                    "report_ids": ids[start : start + batch_size],
                },
                workload=Workload.OFFLINE,
                team_id=team_id,
            )
            or [],
        )
        for document_id, embedding, is_tombstone, inserted_at in rows:
            if is_tombstone or len(embedding) != EMBEDDING_DIMENSIONS:
                continue
            vectors[str(document_id)] = ReportVector(
                embedding=np.asarray(embedding, dtype=np.float32),
                inserted_at=_utc(inserted_at),
            )
    return vectors


def _utc(value: datetime.datetime) -> datetime.datetime:
    # ClickHouse returns a naive DateTime in UTC.
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)
