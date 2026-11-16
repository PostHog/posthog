"""Reads the current vector of each report, for the ranking scorer.

`report_embeddings.py` writes one `document_embeddings` row per rendering of a report. The dataset
dag snapshots every report's latest row fleet-wide with `REPORT_EMBEDDINGS_SQL`. The scorer reads
the same rows for a few reports of one team. The team id is the table's sort-key prefix, so the
read is a point read and not a full scan.

The scorer reads one row that the dataset dag does not: the judged vector of a report that an
unreviewed edit retracted. `SCORABLE_VECTOR_HAVING` holds that rule, and the sweep's candidate scan
uses the same rule, so the sweep only picks reports that the scorer can read a vector for.
"""

import datetime
from collections.abc import Sequence
from typing import Any, cast

from django.conf import settings

import numpy as np

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.report_embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    RETRACTION_REASON_KEY,
    RetractionReason,
)

# The text-embedding-3-small-1536 table, which is the model the report documents are embedded with.
REPORT_EMBEDDINGS_TABLE = "distributed_posthog_document_embeddings_text_embedding_3_small_1536"

# A report is scorable when its newest live row is newer than every tombstone that is not an
# unreviewed edit. The newest row can be an unreviewed-edit tombstone: that tombstone has its own key
# (see `UNREVIEWED_EDIT_TOMBSTONE_OFFSET`), so the judged row it retracts stays in the table. A
# deletion, an unsafe verdict, or a tombstone with no reason (written before reasons existed) that is
# newer than the live row keeps the report unscored, also before a merge removes the live row. With
# no matching row, `maxIf` returns the zero time, so a report with no live row never passes.
# A `GROUP BY team_id, document_id` query appends this, with the `unreviewed_edit` parameter.
SCORABLE_VECTOR_HAVING = f"""
HAVING maxIf(inserted_at, NOT JSONExtractBool(metadata, 'deleted')) > maxIf(
    inserted_at,
    JSONExtractBool(metadata, 'deleted')
    AND JSONExtractString(metadata, '{RETRACTION_REASON_KEY}') != %(unreviewed_edit)s
)
"""

LATEST_REPORT_VECTORS_SQL = f"""
SELECT
    document_id,
    argMaxIf(embedding, inserted_at, NOT JSONExtractBool(metadata, 'deleted')) AS embedding,
    maxIf(inserted_at, NOT JSONExtractBool(metadata, 'deleted')) AS embedding_inserted_at,
    max(inserted_at) AS newest_inserted_at
FROM {REPORT_EMBEDDINGS_TABLE}
WHERE team_id = %(team_id)s
  AND product = %(product)s
  AND document_type = %(document_type)s
  AND rendering = %(rendering)s
  AND document_id IN %(report_ids)s
GROUP BY document_id
{SCORABLE_VECTOR_HAVING}
"""


@frozen
class ReportVector:
    # float32, EMBEDDING_DIMENSIONS wide.
    embedding: np.ndarray
    inserted_at: datetime.datetime
    # True when an unreviewed edit retracted this vector after it landed. The text that the vector
    # embeds is the text before the edit.
    pre_edit: bool = False


def latest_report_vectors(team_id: int, report_ids: Sequence[str], *, rendering: str) -> dict[str, ReportVector]:
    """The newest live vector of each report in `rendering`, keyed by report id.

    A report is absent when it has no live row, or when a tombstone other than an unreviewed edit is
    newer than its newest live row. A report whose newest row is an unreviewed-edit tombstone keeps
    the judged vector before the edit, with `pre_edit` set. Only the ranking scorer may read that
    vector, and only to produce a score. A vector of another width is from another model, so it is
    absent too. One query per batch of `INBOX_RANKING_SCORING_BATCH_SIZE` ids.
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
                    "unreviewed_edit": RetractionReason.UNREVIEWED_EDIT.value,
                },
                workload=Workload.OFFLINE,
                team_id=team_id,
                ch_user=ClickHouseUser.SIGNALS,
            )
            or [],
        )
        for document_id, embedding, inserted_at, newest_inserted_at in rows:
            if len(embedding) != EMBEDDING_DIMENSIONS:
                continue
            vectors[str(document_id)] = ReportVector(
                embedding=np.asarray(embedding, dtype=np.float32),
                inserted_at=_utc(inserted_at),
                pre_edit=newest_inserted_at > inserted_at,
            )
    return vectors


def _utc(value: datetime.datetime) -> datetime.datetime:
    # ClickHouse returns a naive DateTime in UTC.
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)
