"""Per-report signal metadata read off ClickHouse, outside the temporal package.

Signals live as embedding documents in ClickHouse; this module answers "what backs this
report" for synchronous callers (the serializer list view, the auto-start analytics capture)
without importing `products.signals.backend.temporal` — whose `__init__` eagerly loads the
agentic workflow modules, which import `auto_start`, which needs this query: keeping it here
keeps that import graph acyclic.
"""

import re
from dataclasses import dataclass

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# The embedding model whose document rows constitute the signal store; every signals
# ClickHouse query filters on it.
EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536

# Every signal document is emitted under this key triple — the recently-seen lookup in
# wait_for_signal_in_clickhouse_activity relies on exact key equality with the emit sites.
# They live here rather than beside those emit sites so readers outside the temporal package
# (the inbox-ranking dag) can share them without importing the workflow stack.
SIGNAL_DOCUMENT_PRODUCT = "signals"
SIGNAL_DOCUMENT_TYPE = "signal"
SIGNAL_DOCUMENT_RENDERING = "plain"


def _deduped_signals_subquery(
    *,
    include_embedding: bool = False,
    include_content: bool = True,
    extra_where: str | None = None,
    candidate_document_filter: str | None = None,
) -> str:
    """Build the shared signal dedup subquery with an optional extra document_embeddings filter.

    `candidate_document_filter` bounds the dedup to documents that ever matched the filter, via a
    `document_id IN (SELECT DISTINCT ... WHERE <filter>)` prefilter — so the argMax aggregation runs
    over that slice instead of the team's whole signal history (its memory otherwise scales with the
    team's total signal count). Unlike `extra_where`, the filter selects candidate documents but does
    NOT restrict which versions feed the argMax, so "latest version wins" is preserved and the caller's
    own outer filter stays authoritative. Use it for re-groupable fields like `report_id`; use
    `extra_where` only for fields that are stable across a document's versions (e.g. `source_id`).

    `include_content=False` skips the heavy `content` column for callers that only aggregate metadata.

    Raises ValueError if both extra_where and candidate_document_filter are supplied — they are
    mutually exclusive (the extra_where branch returns early and silently drops candidate_document_filter).
    """
    if extra_where and candidate_document_filter:
        raise ValueError("_deduped_signals_subquery: extra_where and candidate_document_filter are mutually exclusive")
    selected_columns = ["document_id"]
    if include_content:
        selected_columns.append("argMax(content, inserted_at) as content")
    selected_columns.append("argMax(metadata, inserted_at) as metadata")
    if include_embedding:
        selected_columns.append("argMax(embedding, inserted_at) as embedding")
    selected_columns.extend(["argMax(timestamp, inserted_at) as timestamp", "max(inserted_at) as latest_inserted_at"])
    selected_columns_sql = ",\n            ".join(selected_columns)

    if extra_where:
        # `extra_where` filters on the raw `metadata` JSON, but this SELECT also exposes
        # `metadata` as an `argMax(...)` alias. HogQL resolves the name in WHERE to that
        # aggregate alias and rejects the query ("aggregate function ... found in WHERE"),
        # so any caller that filtered on `metadata` silently failed. Apply the predicate in
        # a non-aggregating inner scan so it binds to the raw column, then dedupe in the
        # outer aggregate. Pushing the filter down here (vs. the caller's outer query) keeps
        # the dedup scan bounded to the matching rows.
        raw_columns = ["document_id"]
        if include_content:
            raw_columns.append("content")
        raw_columns.append("metadata")
        if include_embedding:
            raw_columns.append("embedding")
        raw_columns.extend(["inserted_at", "timestamp"])
        raw_columns_sql = ",\n                ".join(raw_columns)
        return f"""
        SELECT
            {selected_columns_sql}
        FROM (
            SELECT
                {raw_columns_sql}
            FROM document_embeddings
            WHERE model_name = {{model_name}}
              AND product = 'signals'
              AND document_type = 'signal'
              AND {extra_where}
        )
        GROUP BY document_id
    """

    candidate_bound = ""
    if candidate_document_filter:
        candidate_bound = f"""
          AND document_id IN (
              SELECT DISTINCT document_id
              FROM document_embeddings
              WHERE model_name = {{model_name}}
                AND product = 'signals'
                AND document_type = 'signal'
                AND {candidate_document_filter}
          )"""

    return f"""
        SELECT
            {selected_columns_sql}
        FROM document_embeddings
        WHERE model_name = {{model_name}}
          AND product = 'signals'
          AND document_type = 'signal'{candidate_bound}
        GROUP BY document_id
    """


@dataclass(frozen=True)
class ReportSignalMeta:
    """Per-report signal metadata read off ClickHouse for the inbox list/detail views."""

    source_products: list[str]
    # Raw skill_name slug of the authoring scout (e.g. "signals-scout-error-tracking"), when the
    # report's backing signals carry one. None for pipeline reports and reports emitted before the
    # scout stamped skill_name onto its signals.
    scout_name: str | None


def fetch_source_products_for_reports(team: Team, report_ids: list[str]) -> dict[str, ReportSignalMeta]:
    """Return a mapping of report_id -> `ReportSignalMeta` (distinct source_products + authoring scout).

    Only includes non-deleted signals. Source products are returned in sorted order. `scout_name` is
    any non-empty `extra.skill_name` on the report's signals (all scout-authored signals of a report
    share one), or None.

    Bounds the argMax dedup to documents that ever carried one of these report_ids, instead
    of deduping the team's whole signal history. The unbounded dedup's memory grows with the
    team's total signal count; the candidate-bounded form keeps it proportional to the signals
    in the requested page's reports, which is what flattens the tail on signal-heavy teams.
    The report_id filter stays AFTER the argMax so "latest version wins" holds: a signal that
    was re-grouped to a different report is matched by the candidate scan (it once carried this
    report_id) but excluded by the outer filter (its latest metadata points elsewhere) — the
    same correctness trap fetch_report_ids_for_source_ids documents.
    """
    if not report_ids:
        return {}

    ch_query = """
        SELECT
            report_id,
            arraySort(groupUniqArray(source_product)) as source_products,
            anyIf(skill_name, skill_name != '') as scout_name
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                JSONExtractString(metadata, 'source_product') as source_product,
                JSONExtractString(metadata, 'extra', 'skill_name') as skill_name
            FROM (
                SELECT argMax(metadata, inserted_at) as metadata
                FROM document_embeddings
                WHERE model_name = {model_name}
                  AND product = 'signals'
                  AND document_type = 'signal'
                  AND document_id IN (
                      SELECT DISTINCT document_id
                      FROM document_embeddings
                      WHERE model_name = {model_name}
                        AND product = 'signals'
                        AND document_type = 'signal'
                        AND JSONExtractString(metadata, 'report_id') IN ({report_ids})
                  )
                GROUP BY document_id
            )
        )
        WHERE NOT is_deleted
          AND report_id != ''
          AND report_id IN ({report_ids})
          AND source_product != ''
        GROUP BY report_id
    """

    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsFetchSourceProductsForReports",
        query=ch_query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "report_ids": ast.Tuple(exprs=[ast.Constant(value=rid) for rid in report_ids]),
        },
    )

    return {
        row[0]: ReportSignalMeta(source_products=row[1], scout_name=(row[2] or None))
        for row in (result.results or [])
        if row[0]
    }


@dataclass(frozen=True)
class SourceSliceSignalStats:
    """Aggregate over the latest versions of a source slice's non-deleted signals."""

    signal_count: int
    report_ids: list[str]


def fetch_signal_stats_for_source_slice(
    team: Team, *, source_product: str, source_type: str, extra_equals: dict[str, str]
) -> SourceSliceSignalStats:
    """Count non-deleted signals of one source slice and collect the reports they were grouped into.

    A slice is `(source_product, source_type)` narrowed by equality on `extra` keys (e.g. a Replay
    Vision scanner's `scanner_id`). The slice fields are stable across a document's versions, so they
    go through `_deduped_signals_subquery(extra_where=...)`. The report-id set is uncapped: the
    store's 3-month TTL (restated as a timestamp bound so partition pruning applies) already bounds
    it, and a silent cap would make the counts wrong for exactly the busiest slices.
    """
    conditions = [
        "timestamp >= now() - INTERVAL 3 MONTH",
        "JSONExtractString(metadata, 'source_product') = {source_product}",
        "JSONExtractString(metadata, 'source_type') = {source_type}",
    ]
    placeholders: dict[str, ast.Expr] = {
        "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
        "source_product": ast.Constant(value=source_product),
        "source_type": ast.Constant(value=source_type),
    }
    for index, (key, value) in enumerate(sorted(extra_equals.items())):
        conditions.append(f"JSONExtractString(metadata, 'extra', {{extra_key_{index}}}) = {{extra_value_{index}}}")
        placeholders[f"extra_key_{index}"] = ast.Constant(value=key)
        placeholders[f"extra_value_{index}"] = ast.Constant(value=value)

    deduped = _deduped_signals_subquery(extra_where=" AND ".join(conditions), include_content=False)
    ch_query = f"""
        SELECT
            count() as signal_count,
            groupUniqArrayIf(report_id, report_id != '') as report_ids
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractBool(metadata, 'deleted') as is_deleted
            FROM ({deduped})
        )
        WHERE NOT is_deleted
    """

    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsFetchSignalStatsForSourceSlice",
        query=ch_query,
        team=team,
        placeholders=placeholders,
    )
    rows = result.results or []
    if not rows:
        return SourceSliceSignalStats(signal_count=0, report_ids=[])
    signal_count, report_ids = rows[0]
    return SourceSliceSignalStats(signal_count=signal_count, report_ids=list(report_ids))


@dataclass(frozen=True)
class SignalSourceReference:
    """A link back to the external issue a report's signal was emitted from."""

    source_product: str
    label: str
    url: str


_SOURCE_REFERENCE_CAP = 5

# Labels and URLs come from imported third-party records and end up inside an agent prompt and a
# public PR description, so anything that doesn't look like a plain issue handle or http(s) URL is
# dropped rather than escaped.
_LABEL_RE = re.compile(r"^[A-Za-z0-9#/_.-]{1,64}$")
_URL_RE = re.compile(r"^https?://[^\s()<>\[\]]{1,500}$")


def fetch_source_references_for_report(team: Team, report_id: str) -> list[SignalSourceReference]:
    """Return issue references (label + URL) for the report's non-deleted Linear/GitHub signals.

    Sources whose signals don't carry a stable human-facing URL (e.g. Zendesk's `url` extra is the
    API endpoint, not an agent link) are excluded until they do. Results are deduped by URL, sorted
    for determinism, and capped at `_SOURCE_REFERENCE_CAP` so a signal-heavy report can't flood the
    task prompt. Same candidate-bounded argMax dedup as `fetch_source_products_for_reports`.
    """
    ch_query = """
        SELECT source_product, url, html_url, identifier, issue_number
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                JSONExtractString(metadata, 'source_product') as source_product,
                JSONExtractString(metadata, 'extra', 'url') as url,
                JSONExtractString(metadata, 'extra', 'html_url') as html_url,
                JSONExtractString(metadata, 'extra', 'identifier') as identifier,
                JSONExtractInt(metadata, 'extra', 'number') as issue_number
            FROM (
                SELECT argMax(metadata, inserted_at) as metadata
                FROM document_embeddings
                WHERE model_name = {model_name}
                  AND product = 'signals'
                  AND document_type = 'signal'
                  AND document_id IN (
                      SELECT DISTINCT document_id
                      FROM document_embeddings
                      WHERE model_name = {model_name}
                        AND product = 'signals'
                        AND document_type = 'signal'
                        AND JSONExtractString(metadata, 'report_id') = {report_id}
                  )
                GROUP BY document_id
            )
        )
        WHERE NOT is_deleted
          AND report_id = {report_id}
          AND source_product IN ('linear', 'github')
    """

    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsFetchSourceReferencesForReport",
        query=ch_query,
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "report_id": ast.Constant(value=report_id),
        },
    )

    references: list[SignalSourceReference] = []
    seen_urls: set[str] = set()
    for source_product, url, html_url, identifier, issue_number in result.results or []:
        if source_product == "linear":
            ref_url, label = url, (identifier if identifier and _LABEL_RE.match(identifier) else "Linear issue")
        else:
            ref_url, label = html_url, (f"#{issue_number}" if issue_number else "GitHub issue")
        ref_url = (ref_url or "").strip()
        if not _URL_RE.match(ref_url) or ref_url in seen_urls:
            continue
        seen_urls.add(ref_url)
        references.append(SignalSourceReference(source_product=source_product, label=label, url=ref_url))

    references.sort(key=lambda ref: (ref.source_product, ref.label, ref.url))
    return references[:_SOURCE_REFERENCE_CAP]
