import json
import datetime

from unittest.mock import patch

from posthog.clickhouse.client import sync_execute

from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.report_embedding_reader import REPORT_EMBEDDINGS_TABLE
from products.signals.backend.report_embeddings import (
    EMBEDDING_RENDERING_TITLE_SUMMARY,
    RetractionReason,
    emit_report_tombstone,
)

# The producer is imported inside the emit helpers, so it is patched where it is defined.
EMIT_REQUEST_PATH = "posthog.api.embedding_worker.emit_embedding_request"


def _naive_utc(value: datetime.datetime) -> datetime.datetime:
    return value.astimezone(datetime.UTC).replace(tzinfo=None) if value.tzinfo else value


def insert_report_tombstone(
    *,
    team_id: int,
    report_id: str,
    created_at: datetime.datetime,
    inserted_at: datetime.datetime,
    reason: RetractionReason,
) -> None:
    # Takes the key, content and metadata from the real writer, so a change to the tombstone key
    # reaches the ClickHouse tests that read it.
    with patch(EMIT_REQUEST_PATH) as emit_request:
        emit_report_tombstone(
            team_id=team_id,
            report_id=report_id,
            created_at=created_at,
            reason=reason,
            renderings=(EMBEDDING_RENDERING_TITLE_SUMMARY,),
        )
    row = emit_request.call_args.kwargs
    sync_execute(
        f"""
        INSERT INTO {REPORT_EMBEDDINGS_TABLE} (
            team_id, product, document_type, rendering, document_id,
            timestamp, inserted_at, content, metadata, embedding,
            _timestamp, _offset, _partition
        ) VALUES
        """,
        [
            (
                row["team_id"],
                row["product"],
                row["document_type"],
                row["rendering"],
                row["document_id"],
                _naive_utc(row["timestamp"]),
                _naive_utc(inserted_at),
                row["content"],
                json.dumps(row["metadata"]),
                [0.0] * EMBEDDING_DIMENSIONS,
                _naive_utc(inserted_at),
                0,
                0,
            )
        ],
        flush=False,
        team_id=team_id,
    )
