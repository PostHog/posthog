"""Search a project's inbox reports by relevance, for agents checking whether a report already exists.

A keyword search requires every query term in the title or the summary, and leans on the trigram
indexes on both columns. A semantic search ranks the newest `title_summary_v1` vector of each report by
its distance to the query. A hybrid search merges both rankings with reciprocal rank fusion. A report's
vectors expire 3 months after it was created, so an older report can match on keywords only, and a
failed semantic read leaves a hybrid search with the keyword ranking.

Both sides return only rows of the queryset the caller passes, which carries the team scope and the
caller's filters, so neither side can surface a report the list endpoint would not.
"""

import json
import time
import uuid
import datetime
from collections.abc import Sequence
from typing import Any, cast

from django.db import models
from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

import structlog
from opentelemetry import trace
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_random

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseAtCapacity
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.artefact_schemas import priority_from_judgment
from products.signals.backend.hybrid_search import SearchMode, SemanticSearchUnavailable, reciprocal_rank_fusion
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.report_embedding_reader import REPORT_EMBEDDINGS_TABLE
from products.signals.backend.report_embeddings import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_PRODUCT,
    EMBEDDING_RENDERING_TITLE_SUMMARY,
)
from products.signals.backend.signal_metadata import EMBEDDING_MODEL

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

SEARCH_FLAG = "inbox-reports-search"
DEFAULT_LIMIT = 10
MAX_LIMIT = 25
# Each side ranks at most this many reports before fusion.
CANDIDATES = 100
# A report's vectors expire 3 months after it was created (the table TTL), so an older report cannot match
# semantically. 93 days covers the longest 3-month span.
VECTOR_LIFETIME = datetime.timedelta(days=93)
# The newest eligible reports the vector read may consider. It bounds the id list sent to ClickHouse. A team
# that creates more reports than this in one vector lifetime finds its oldest ones on keywords only.
MAX_SEMANTIC_REPORTS = 10_000
# Every term is one more pair of trigram lookups, so a pasted paragraph must not become dozens of them.
MAX_TERMS = 8
SNIPPET_RADIUS = 120
EMBEDDING_TIMEOUT_S = 10.0
# A stalled read must end inside the MCP request deadline, so that a hybrid search can still return its keyword ranking.
VECTOR_READ_MAX_EXECUTION_S = 10
# All signals queries share one ClickHouse user, so its concurrent-query limit refuses reads in short bursts.
# ClickHouse refuses such a read immediately, so the added attempts stay well inside the MCP request deadline.
# A read that reaches its time limit gets no second attempt, because the caller already waited for the full limit.
VECTOR_READ_ATTEMPTS = 3
VECTOR_READ_RETRY_WAIT_S = (0.5, 2.0)
# Quotes and sentence punctuation around a word, which would otherwise have to match literally.
_TERM_EDGES = "\"'`.,;:!?()[]{}<>"

# The same newest-row rule as `report_embedding_reader.LATEST_REPORT_VECTORS_SQL`: a report whose newest
# row is a tombstone is dropped, and an older live row never stands in for it.
NEAREST_REPORTS_SQL = f"""
SELECT document_id, cosineDistance(embedding, %(embedding)s) AS distance
FROM (
    SELECT
        document_id,
        argMax(embedding, inserted_at) AS embedding,
        argMax(JSONExtractBool(metadata, 'deleted'), inserted_at) AS is_tombstone
    FROM {REPORT_EMBEDDINGS_TABLE}
    WHERE team_id = %(team_id)s
      AND product = %(product)s
      AND document_type = %(document_type)s
      AND rendering = %(rendering)s
      AND document_id IN %(report_ids)s
    GROUP BY document_id
)
WHERE NOT is_tombstone AND length(embedding) = %(dimensions)s
ORDER BY distance ASC
LIMIT %(limit)s
"""


class ReportMatchKind(models.TextChoices):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


@frozen
class ReportSearchHit:
    id: uuid.UUID
    title: str | None
    status: str
    priority: str | None
    updated_at: datetime.datetime
    summary_snippet: str
    dismissal_reason: str | None
    dismissal_note: str | None
    match_kinds: tuple[ReportMatchKind, ...]
    score: float


@frozen
class ReportSearchResult:
    results: tuple[ReportSearchHit, ...]
    # False when a hybrid search fell back to keywords, or when the search did not ask for vectors.
    semantic_available: bool


def search_enabled(team: Team) -> bool:
    organization_id = str(team.organization_id)
    try:
        return (
            feature_enabled_or_false(
                SEARCH_FLAG,
                organization_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                send_feature_flag_events=False,
                only_evaluate_locally=True,
            )
            is True
        )
    except Exception:
        logger.exception("inbox_reports_search_flag_check_failed", team_id=team.id)
        return False


def keyword_terms(query: str) -> list[str]:
    """The query's words that the trigram indexes can look up, lowercased and deduplicated.

    A word with no indexable text, such as `a` or `is`, is left out rather than required, because
    Postgres would answer it by reading every report of the team.
    """
    # Deferred: the scout harness serializers import the signals serializers, which import this module.
    from products.signals.backend.scout_harness.serializers import TRIGRAM_INDEXABLE_TEXT  # noqa: PLC0415

    words = (word.strip(_TERM_EDGES).lower() for word in query.split())
    return list(dict.fromkeys(word for word in words if TRIGRAM_INDEXABLE_TEXT.search(word)))[:MAX_TERMS]


def search_reports(
    team: Team,
    reports: QuerySet[SignalReport],
    *,
    query: str,
    search_mode: SearchMode = SearchMode.HYBRID,
    limit: int = DEFAULT_LIMIT,
) -> ReportSearchResult:
    """Rank the reports in `reports` that match `query`, best first.

    `reports` must already be scoped to `team` and filtered as the caller wants. Raises
    `SemanticSearchUnavailable` only for a semantic search, because a hybrid one keeps its keyword ranking.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    span = trace.get_current_span()
    terms = keyword_terms(query)
    span.set_attribute("signals.reports.search.mode", search_mode.value)
    span.set_attribute("signals.reports.search.term_count", len(terms))

    keyword_ranking: list[uuid.UUID] = []
    if search_mode != SearchMode.SEMANTIC and terms:
        keyword_ranking = _keyword_ranking(reports, terms)

    semantic_ranking: list[uuid.UUID] = []
    semantic_available = False
    if search_mode != SearchMode.KEYWORD:
        try:
            semantic_ranking = _semantic_ranking(team, query, reports)
            semantic_available = True
        except Exception as error:
            logger.exception("inbox_reports_search_semantic_failed", team_id=team.id)
            if search_mode == SearchMode.SEMANTIC:
                raise SemanticSearchUnavailable() from error
    span.set_attribute("signals.reports.search.keyword_count", len(keyword_ranking))
    span.set_attribute("signals.reports.search.semantic_count", len(semantic_ranking))
    span.set_attribute("signals.reports.search.semantic_available", semantic_available)

    scores = reciprocal_rank_fusion([keyword_ranking, semantic_ranking])
    top = sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))[:limit]
    keyword_ids, semantic_ids = set(keyword_ranking), set(semantic_ranking)
    rows = {report.id: report for report in _hydrate(reports, [report_id for report_id, _ in top])}
    hits = [
        _hit(
            rows[report_id],
            score=round(score, 6),
            terms=terms,
            match_kinds=(
                *((ReportMatchKind.KEYWORD,) if report_id in keyword_ids else ()),
                *((ReportMatchKind.SEMANTIC,) if report_id in semantic_ids else ()),
            ),
        )
        for report_id, score in top
        # A report deleted between the ranking and this read drops out.
        if report_id in rows
    ]
    return ReportSearchResult(results=tuple(hits), semantic_available=semantic_available)


def _keyword_ranking(reports: QuerySet[SignalReport], terms: Sequence[str]) -> list[uuid.UUID]:
    """Reports that hold every term, those with the most terms in the title first, then the most recently updated."""
    condition = Q()
    for term in terms:
        condition &= Q(title__icontains=term) | Q(summary__icontains=term)
    rows = list(reports.filter(condition).order_by("-updated_at").values_list("id", "title")[:CANDIDATES])
    # A stable sort, so reports with the same title count keep their recency order.
    rows.sort(key=lambda row: -sum(term in (row[1] or "").lower() for term in terms))
    return [report_id for report_id, _ in rows]


def _semantic_ranking(team: Team, query: str, reports: QuerySet[SignalReport]) -> list[uuid.UUID]:
    # Deferred: `posthog.api` loads the product routes, which import this module through the signals views.
    from posthog.api.embedding_worker import generate_embedding  # noqa: PLC0415

    # The caller's filters apply before the vector read limits to the nearest reports. Filtering the nearest
    # reports afterwards could drop every one of them while eligible reports with vectors exist further out.
    eligible = [
        str(report_id)
        for report_id in reports.filter(created_at__gte=timezone.now() - VECTOR_LIFETIME)
        .order_by("-created_at")
        .values_list("id", flat=True)[:MAX_SEMANTIC_REPORTS]
    ]
    if not eligible:
        return []
    embedding = generate_embedding(team, query, model=EMBEDDING_MODEL.value, timeout=EMBEDDING_TIMEOUT_S).embedding
    tag_queries(product=Product.SIGNALS, feature=Feature.ENRICHMENT, team_id=team.id, query_type="inbox_report_search")
    with tracer.start_as_current_span("signals.reports.search.vector_read") as span:
        started = time.monotonic()
        read = Retrying(
            retry=retry_if_exception_type(ClickHouseAtCapacity),
            stop=stop_after_attempt(VECTOR_READ_ATTEMPTS),
            wait=wait_random(*VECTOR_READ_RETRY_WAIT_S),
            reraise=True,
        )
        rows = cast(
            list[tuple[Any, ...]],
            read(
                sync_execute,
                NEAREST_REPORTS_SQL,
                {
                    "embedding": embedding,
                    "team_id": team.id,
                    "product": EMBEDDING_PRODUCT,
                    "document_type": EMBEDDING_DOCUMENT_TYPE,
                    "rendering": EMBEDDING_RENDERING_TITLE_SUMMARY,
                    "report_ids": eligible,
                    "dimensions": EMBEDDING_DIMENSIONS,
                    "limit": CANDIDATES,
                },
                settings={"max_execution_time": VECTOR_READ_MAX_EXECUTION_S, "timeout_overflow_mode": "throw"},
                # Scout runs make most of these calls, and no person waits on them.
                workload=Workload.OFFLINE,
                team_id=team.id,
                ch_user=ClickHouseUser.SIGNALS,
            )
            or [],
        )
        span.set_attribute("signals.reports.search.vector_read.duration_ms", round((time.monotonic() - started) * 1000))
        span.set_attribute("signals.reports.search.vector_read.rows", len(rows))
        span.set_attribute("signals.reports.search.vector_read.eligible", len(eligible))
        span.set_attribute("signals.reports.search.vector_read.attempts", read.statistics["attempt_number"])
    return [report_id for report_id in (_as_uuid(document_id) for document_id, _ in rows) if report_id is not None]


def _as_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _hydrate(reports: QuerySet[SignalReport], report_ids: Sequence[uuid.UUID]) -> list[SignalReport]:
    return list(
        reports.filter(id__in=report_ids)
        .only("id", "title", "summary", "status", "updated_at")
        .prefetch_related(
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(
                    type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
                ).order_by("-created_at"),
                to_attr="search_priority_artefacts",
            ),
            Prefetch(
                "artefacts",
                queryset=SignalReportArtefact.objects.filter(type=SignalReportArtefact.ArtefactType.DISMISSAL).order_by(
                    "-created_at"
                ),
                to_attr="search_dismissal_artefacts",
            ),
        )
    )


def _hit(
    report: SignalReport, *, score: float, terms: Sequence[str], match_kinds: tuple[ReportMatchKind, ...]
) -> ReportSearchHit:
    priority_artefacts = cast(list[SignalReportArtefact], getattr(report, "search_priority_artefacts", []))
    dismissal_artefacts = cast(list[SignalReportArtefact], getattr(report, "search_dismissal_artefacts", []))
    dismissal = _dismissal(dismissal_artefacts[0]) if dismissal_artefacts else {}
    return ReportSearchHit(
        id=report.id,
        title=report.title,
        status=report.status,
        priority=priority_from_judgment(priority_artefacts[0].content) if priority_artefacts else None,
        updated_at=report.updated_at,
        summary_snippet=summary_snippet(report.summary, terms),
        dismissal_reason=_text(dismissal.get("reason")),
        dismissal_note=_text(dismissal.get("note")),
        match_kinds=match_kinds,
        score=score,
    )


def summary_snippet(summary: str | None, terms: Sequence[str]) -> str:
    """A short excerpt of `summary` around the first term it holds, or its opening when it holds none."""
    text = " ".join((summary or "").split())
    lowered = text.lower()
    positions = [position for term in terms if (position := lowered.find(term)) >= 0]
    start = max(0, min(positions) - SNIPPET_RADIUS) if positions else 0
    end = min(len(text), start + 2 * SNIPPET_RADIUS)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def _dismissal(artefact: SignalReportArtefact) -> dict[str, Any]:
    try:
        data = json.loads(artefact.content)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
