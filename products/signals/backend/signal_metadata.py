"""Per-report signal metadata read off ClickHouse, outside the temporal package.

Signals live as embedding documents in ClickHouse; this module answers "what backs this
report" for synchronous callers (the serializer list view, the auto-start analytics capture)
without importing `products.signals.backend.temporal` — whose `__init__` eagerly loads the
agentic workflow modules, which import `auto_start`, which needs this query: keeping it here
keeps that import graph acyclic.
"""

from dataclasses import dataclass

from posthog.schema import EmbeddingModelName

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# The embedding model whose document rows constitute the signal store; every signals
# ClickHouse query filters on it.
EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536


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
