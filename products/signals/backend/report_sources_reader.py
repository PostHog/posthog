"""Reads the live source products of each report's signals, for the ranking scorer.

The dataset dag logs every signal emission fleet-wide (`SIGNAL_EMBEDDINGS_SQL`), and training takes
the latest emission per signal as of a moment. The scorer needs the same latest emission per signal
for a few reports of one team at scoring time, so this read takes it with the team and the report
ids added. The team id is the table's sort-key prefix, so the read stays inside one team's rows.
"""

from collections.abc import Sequence
from typing import Any, cast

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload

from products.signals.backend.report_embedding_reader import REPORT_EMBEDDINGS_TABLE
from products.signals.backend.signal_metadata import (
    SIGNAL_DOCUMENT_PRODUCT,
    SIGNAL_DOCUMENT_RENDERING,
    SIGNAL_DOCUMENT_TYPE,
)

# The candidate scan keeps the dedup to the signals that ever named one of the reports. The outer
# filter reads the report from the latest emission, so a signal regrouped to another report drops out.
LIVE_REPORT_SOURCES_SQL = f"""
SELECT report_id, source_product
FROM (
    SELECT
        nullIf(JSONExtractString(metadata, 'report_id'), '') AS report_id,
        nullIf(JSONExtractString(metadata, 'source_product'), '') AS source_product,
        JSONExtractBool(metadata, 'deleted') AS is_deleted
    FROM (
        SELECT argMax(metadata, inserted_at) AS metadata
        FROM {REPORT_EMBEDDINGS_TABLE}
        WHERE team_id = %(team_id)s
          AND product = %(product)s
          AND document_type = %(document_type)s
          AND rendering = %(rendering)s
          AND document_id IN (
              SELECT DISTINCT document_id
              FROM {REPORT_EMBEDDINGS_TABLE}
              WHERE team_id = %(team_id)s
                AND product = %(product)s
                AND document_type = %(document_type)s
                AND rendering = %(rendering)s
                AND JSONExtractString(metadata, 'report_id') IN %(report_ids)s
          )
        GROUP BY document_id
    )
)
WHERE NOT is_deleted
  AND report_id IN %(report_ids)s
"""


def live_report_sources(team_id: int, report_ids: Sequence[str]) -> list[tuple[str, str | None]]:
    """One `(report_id, source_product)` row per live signal of `report_ids`. The product is None when
    the signal's latest emission names none. A report with no live signal has no row. One query per
    batch of `INBOX_RANKING_SCORING_BATCH_SIZE` ids."""
    ids = list(dict.fromkeys(str(report_id) for report_id in report_ids))
    batch_size = settings.INBOX_RANKING_SCORING_BATCH_SIZE
    sources: list[tuple[str, str | None]] = []
    for start in range(0, len(ids), batch_size):
        tag_queries(
            product=Product.SIGNALS,
            feature=Feature.ENRICHMENT,
            team_id=team_id,
            query_type="inbox_ranking_report_sources",
        )
        rows = cast(
            list[tuple[Any, ...]],
            sync_execute(
                LIVE_REPORT_SOURCES_SQL,
                {
                    "team_id": team_id,
                    "product": SIGNAL_DOCUMENT_PRODUCT,
                    "document_type": SIGNAL_DOCUMENT_TYPE,
                    "rendering": SIGNAL_DOCUMENT_RENDERING,
                    "report_ids": ids[start : start + batch_size],
                },
                workload=Workload.OFFLINE,
                team_id=team_id,
                ch_user=ClickHouseUser.SIGNALS,
            )
            or [],
        )
        sources.extend((str(report_id), source_product) for report_id, source_product in rows)
    return sources
