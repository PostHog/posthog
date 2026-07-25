"""Report-level embeddings: one `document_embeddings` row per `SignalReport`.

The grouping pipeline already embeds each *signal* that backs a report (`document_type='signal'`).
This module embeds the *report itself* — the LLM-written title and summary the inbox shows — so a
report has a vector of its own instead of only a cloud of constituent-signal vectors that every
reader has to re-aggregate.

That vector is the feature-side building block for the inbox ranking model. The label side already
exists: `capture_status_change_analytics` in `receivers.py` emits `signal_report_status_changed` for
every resolve, dismissal, and snooze.
"""

from datetime import datetime
from typing import Any

from posthog.api.embedding_worker import emit_embedding_request
from posthog.schema_enums import EmbeddingModelName

EMBEDDING_PRODUCT = "signals"
EMBEDDING_DOCUMENT_TYPE = "report"

# Versioned, unlike the 'plain' rendering the signal rows use. A signal's content is verbatim source
# text, but a report document is a composition of fields we expect to grow (source products, priority,
# excerpts of the strongest signals). `rendering` is part of the table's ORDER BY, so bumping this to
# a v2 lets both compositions sit in the table at once and be compared, rather than v2 rows silently
# replacing the v1 row for the same report.
EMBEDDING_RENDERING = "title_summary_v1"


def render_report_document(title: str | None, summary: str | None) -> str | None:
    """Render a report's text for embedding, or None when it has nothing worth embedding yet.

    A report exists before its text does: the grouping pipeline creates the row, and title/summary
    are written either by the matcher or by the summary workflow on `IN_PROGRESS -> READY`. Embedding
    an empty document would put a meaningless vector in the index under the report's id, which every
    later re-emission then has to displace.
    """
    rendered_title = (title or "").strip()
    rendered_summary = (summary or "").strip()
    if not rendered_title and not rendered_summary:
        return None
    return "\n\n".join(part for part in (rendered_title, rendered_summary) if part)


def emit_report_embedding(
    *, team_id: int, report_id: str, content: str, created_at: datetime, deleted: bool = False
) -> None:
    """Queue a report embedding for the worker, superseding any previous vector for the same report.

    `created_at` becomes the row's `timestamp`, rather than the emission time, on purpose. The
    underlying table partitions by `toMonday(timestamp)` and orders by `toDate(timestamp)`, so a
    re-emission stamped with the current time lands in a different partition and sits *alongside* the
    report's earlier row instead of superseding it in the ReplacingMergeTree. Pinning the timestamp to
    report creation keeps every version of a report's document on one key, so the latest `inserted_at`
    wins. The grouping pipeline's signal soft-delete relies on the same property.

    The cost of pinning is that the table's `timestamp + 3 MONTH` TTL is measured from report creation,
    so a report that stays open longer than that loses its vector while still live. Consumers must
    therefore snapshot features as they are produced rather than recompute them retroactively.

    `deleted` writes the tombstone that mirrors `soft_delete_report_signals`: the same row re-emitted
    with `metadata.deleted = true` so it replaces the live one. Readers must filter it out the same way
    every signals query already does, with `NOT JSONExtractBool(metadata, 'deleted')`. Note this makes
    the row filterable rather than erasing its text, exactly as the signal tombstone does.
    """
    metadata: dict[str, Any] = {"report_id": report_id}
    if deleted:
        metadata["deleted"] = True

    emit_embedding_request(
        content=content,
        team_id=team_id,
        product=EMBEDDING_PRODUCT,
        document_type=EMBEDDING_DOCUMENT_TYPE,
        rendering=EMBEDDING_RENDERING,
        document_id=report_id,
        models=[model.value for model in EmbeddingModelName],
        timestamp=created_at,
        # Deliberately minimal. Metadata is only refreshed when the report's text changes or it is
        # deleted, so mutable state (status, priority, signal_count) would go stale here with nothing
        # to signal it; those belong in a join against Postgres or the `signal_report_status_changed`
        # stream. `report_id` duplicates `document_id` so a query can JSONExtract it uniformly across
        # report rows and the signal rows that already carry it in metadata.
        metadata=metadata,
    )
