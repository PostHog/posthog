"""Report-level embeddings: one `document_embeddings` row per rendering of a `SignalReport`.

The grouping pipeline already embeds each *signal* that backs a report (`document_type='signal'`).
This module embeds the *report itself*, the LLM-written title and summary the inbox shows, so a
report has vectors of its own instead of only a cloud of constituent-signal vectors that every
reader has to re-aggregate. Each rendering in `EMBEDDING_RENDERINGS` is a separate row, under the
report's id.

Those vectors are the feature-side building block for the inbox ranking model. The label side
already exists: `capture_status_change_analytics` in `receivers.py` emits
`signal_report_status_changed` for every resolve, dismissal, and snooze.
"""

from collections.abc import Mapping
from datetime import datetime

from posthog.schema_enums import EmbeddingModelName

EMBEDDING_PRODUCT = "signals"
EMBEDDING_DOCUMENT_TYPE = "report"

# Versioned, unlike the 'plain' rendering the signal rows use. A signal's content is verbatim source
# text, but a report document is a composition of fields we expect to grow (source products, priority,
# excerpts of the strongest signals). `rendering` is part of the table's ORDER BY, so several
# compositions sit in the table at once and can be compared, rather than one silently replacing
# another for the same report.
EMBEDDING_RENDERING_TITLE_SUMMARY = "title_summary_v1"
# The title alone, because the title is the only text the inbox shows before someone opens a report.
# Embedded beside the composed document so the ranking model can measure what the summary adds to a
# prediction of whether a report is opened, instead of reading one vector that mixes the two.
EMBEDDING_RENDERING_TITLE = "title_v1"

# Every rendering a report may hold a row for. The retraction path walks this, because `rendering` is
# part of the key: a tombstone for one rendering leaves every other rendering's content live until the
# TTL expires it. Whoever adds a rendering adds it here too.
EMBEDDING_RENDERINGS = (EMBEDDING_RENDERING_TITLE_SUMMARY, EMBEDDING_RENDERING_TITLE)

# Tombstones carry this fixed text instead of the report's own, which is what makes it safe to write
# one without first knowing whether a live row exists. A tombstone only has to match the ReplacingMergeTree
# key (team, date(timestamp), product, document_type, model_name, rendering, document_id), and content
# is not part of that key, so the placeholder supersedes a live row just as well as a copy of its text
# would. Carrying the real text instead would mean a speculative tombstone could *introduce* content the
# safety judge rejected, and an empty string would put an embedding of "" through the worker. This is a
# deliberate divergence from `soft_delete_report_signals`, which re-emits signal text verbatim.
TOMBSTONE_CONTENT = "[deleted report]"


def render_report_documents(title: str | None, summary: str | None) -> dict[str, str]:
    """Render a report's documents, keyed by rendering, dropping any that has nothing to embed yet.

    A report exists before its text does: the grouping pipeline creates the row, and title/summary
    are written either by the matcher or by the summary workflow on `IN_PROGRESS -> READY`. Embedding
    an empty document would put a meaningless vector in the index under the report's id, which every
    later re-emission then has to displace. A report that has a summary but no title yet gets the
    composed document only, so the title rendering starts once there is a title to embed.
    """
    rendered_title = (title or "").strip()
    parts = [part for part in (rendered_title, (summary or "").strip()) if part]
    documents: dict[str, str] = {}
    if parts:
        documents[EMBEDDING_RENDERING_TITLE_SUMMARY] = "\n\n".join(parts)
    if rendered_title:
        documents[EMBEDDING_RENDERING_TITLE] = rendered_title
    return documents


def _emit(*, team_id: int, report_id: str, rendering: str, content: str, created_at: datetime, deleted: bool) -> None:
    """Queue one report document for the embedding worker.

    `created_at` becomes the row's `timestamp`, rather than the emission time, on purpose. The
    underlying table partitions by `toMonday(timestamp)` and orders by `toDate(timestamp)`, so a
    re-emission stamped with the current time lands in a different partition and sits *alongside* the
    report's earlier row instead of superseding it in the ReplacingMergeTree. Pinning the timestamp to
    report creation keeps every version of a report's document on one key, so the latest `inserted_at`
    wins. The grouping pipeline's signal soft-delete relies on the same property.

    The cost of pinning is that the table's `timestamp + 3 MONTH` TTL is measured from report creation,
    so a report that stays open longer than that loses its vector while still live. Consumers must
    therefore snapshot features as they are produced rather than recompute them retroactively.
    """
    # Deferred so `django.setup()` does not pay for the embedding producer: `receivers.py` is imported
    # from SignalsConfig.ready(), and this module's only heavy dependency is the Kafka/HTTP/ClickHouse
    # chain behind emit_embedding_request, which only matters once a report is actually embedded.
    from posthog.api.embedding_worker import emit_embedding_request  # noqa: PLC0415

    metadata: dict[str, object] = {"report_id": report_id}
    if deleted:
        metadata["deleted"] = True

    emit_embedding_request(
        content=content,
        team_id=team_id,
        product=EMBEDDING_PRODUCT,
        document_type=EMBEDDING_DOCUMENT_TYPE,
        rendering=rendering,
        document_id=report_id,
        models=[model.value for model in EmbeddingModelName],
        timestamp=created_at,
        # Deliberately minimal. Metadata is only refreshed when the report's text changes or the row is
        # retracted, so mutable state (status, priority, signal_count) would go stale here with nothing
        # to signal it; those belong in a join against Postgres or the `signal_report_status_changed`
        # stream. `report_id` duplicates `document_id` so a query can JSONExtract it uniformly across
        # report rows and the signal rows that already carry it in metadata.
        metadata=metadata,
    )


def emit_report_embeddings(*, team_id: int, report_id: str, documents: Mapping[str, str], created_at: datetime) -> None:
    """Publish the given renderings of the report, superseding any previous vector for each of them.

    Callers pass only the renderings whose text changed. A rendering left out keeps the row it already
    has, which is what lets a summary-only edit skip the title vector it would rewrite identically.
    """
    for rendering, content in documents.items():
        _emit(
            team_id=team_id,
            report_id=report_id,
            rendering=rendering,
            content=content,
            created_at=created_at,
            deleted=False,
        )


def emit_report_tombstone(
    *,
    team_id: int,
    report_id: str,
    created_at: datetime,
    renderings: tuple[str, ...] = EMBEDDING_RENDERINGS,
) -> None:
    """Retract all renderings by default, or a specified subset when report text is removed.

    Callers do not need to know if a live row exists. Because the tombstone carries `TOMBSTONE_CONTENT`
    rather than the report's text, writing one for a report that was never embedded costs an extra row
    and leaks nothing, which is what lets every retraction path (deletion, an unsafe verdict, an
    unreviewed edit) emit unconditionally instead of guessing. The same property makes it safe to
    retract every rendering rather than the subset the report happens to hold.

    Readers must filter these out the way every signals query already does, with
    `NOT JSONExtractBool(metadata, 'deleted')`.
    """
    for rendering in renderings:
        _emit(
            team_id=team_id,
            report_id=report_id,
            rendering=rendering,
            content=TOMBSTONE_CONTENT,
            created_at=created_at,
            deleted=True,
        )
