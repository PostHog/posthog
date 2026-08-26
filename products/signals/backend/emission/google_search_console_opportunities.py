"""Google Search Console search-opportunity signals.

Unlike the ticket/issue sources, Google Search Console does not sync ready-made actionable
records — it syncs *search performance* rows (one per query x landing page x day, with clicks,
impressions, CTR, and average position). This emitter turns the subset of those rows that
represent a fixable problem into signals: pages that already rank on the first pages of Google
for a query and get plenty of impressions, yet are rarely clicked. A click-through rate that low
for that ranking almost always points at a weak search result title/meta description (or a page
that doesn't match intent) — something the user can fix to recover organic traffic.

Two things make this source need a bespoke `record_fetcher` instead of the generic
`data_warehouse_record_fetcher`:

1. The warehouse `date` column is the *search day*, which Google publishes ~3 days in arrears —
   it is not comparable to the pipeline's wall-clock `last_synced_at` (`schema.last_synced_at`
   is the job start time). The generic fetcher's `WHERE date > last_synced_at` would match
   nothing. We look back over a fixed trailing window of available data instead.
2. That trailing window re-surfaces the same recent days on every sync, so we dedupe against
   `SignalEmissionRecord` (same approach as the conversations fetcher) to emit each
   (day, page, query) opportunity exactly once.
"""

from typing import Any

from django.utils import timezone

import structlog

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig
from products.signals.backend.models import SignalEmissionRecord
from products.web_analytics.backend.facade import (
    GSC_FIELDS,
    GSC_LOOKBACK_DAYS,
    OPPORTUNITY_WHERE_CLAUSE,
    build_search_opportunity_description,
    search_opportunity_date,
    search_opportunity_source_id,
    search_opportunity_weight,
)

logger = structlog.get_logger(__name__)

SOURCE_PRODUCT = "google_search_console"
SOURCE_TYPE = "search_opportunity"

# The warehouse table we watch. by_query_page carries the query context that makes each signal
# actionable ("users searching for X see your page but don't click"). It is synced by default
# for the source (should_sync_default=True in the GSC source settings).
SCHEMA_NAME = "search_analytics_by_query_page"


def google_search_console_opportunity_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        page = record["page"]
        query = record["query"]
    except KeyError as e:
        msg = f"Google Search Console record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not page or not query:
        logger.info(
            "Ignoring Google Search Console row with empty page or query",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None

    date_str = search_opportunity_date(record.get("date"))
    impressions = int(record.get("impressions") or 0)
    clicks = int(record.get("clicks") or 0)
    ctr = float(record.get("ctr") or 0.0)
    position = float(record.get("position") or 0.0)

    return SignalEmitterOutput(
        source_product=SOURCE_PRODUCT,
        source_type=SOURCE_TYPE,
        source_id=search_opportunity_source_id(record),
        description=build_search_opportunity_description(page, query, date_str, impressions, clicks, ctr, position),
        weight=search_opportunity_weight(impressions),
        extra={
            "page": page,
            "query": query,
            "date": date_str,
            "clicks": clicks,
            "impressions": impressions,
            "ctr": ctr,
            "position": position,
        },
    )


def google_search_console_record_fetcher(
    team: Team,
    config: SignalSourceTableConfig,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fetch recent opportunity rows via HogQL and dedupe against already-emitted signals."""
    table_name: str = context["table_name"]
    extra: dict[str, Any] = context.get("extra", {})
    # No external input here — the where clause and table name are internal constants — so f-string
    # interpolation is safe (matches data_warehouse_record_fetcher's rationale).
    fields_sql = ", ".join(config.fields)
    query = f"""
        SELECT {fields_sql}
        FROM {table_name}
        WHERE date > now() - interval {GSC_LOOKBACK_DAYS} day AND {config.where_clause}
        ORDER BY date DESC, impressions DESC
        LIMIT {config.max_records}
    """
    logger.info(
        "Querying Google Search Console opportunities for signal emission",
        table_name=table_name,
        lookback_days=GSC_LOOKBACK_DAYS,
        where_clause=config.where_clause,
        max_records=config.max_records,
        signals_type="data-import-signals",
        **extra,
    )
    try:
        result = execute_hogql_query(
            query=parse_select(query),
            team=team,
            query_type="EmitSignalsNewRecords",
            bypass_warehouse_access_control=True,
        )
    except Exception as e:
        logger.exception(f"Error querying Google Search Console opportunities: {e}", **extra)
        # Raise so the activity retries rather than silently dropping a day's opportunities.
        raise
    if not result.results or not result.columns:
        return []

    rows = [dict(zip(result.columns, row)) for row in result.results]
    source_ids = [search_opportunity_source_id(r) for r in rows]
    already_emitted = set(
        SignalEmissionRecord.objects.filter(
            team=team,
            source_product=config.source_product,
            source_type=config.source_type,
            source_id__in=source_ids,
        ).values_list("source_id", flat=True)
    )
    new_rows = [row for row, source_id in zip(rows, source_ids) if source_id not in already_emitted]
    if not new_rows:
        return []

    now = timezone.now()
    SignalEmissionRecord.objects.bulk_create(
        [
            SignalEmissionRecord(
                team=team,
                source_product=config.source_product,
                source_type=config.source_type,
                source_id=search_opportunity_source_id(row),
                emitted_at=now,
            )
            for row in new_rows
        ],
        ignore_conflicts=True,
    )
    return new_rows


GOOGLE_SEARCH_CONSOLE_CONFIG = SignalSourceTableConfig(
    source_product=SOURCE_PRODUCT,
    source_type=SOURCE_TYPE,
    emitter=google_search_console_opportunity_emitter,
    record_fetcher=google_search_console_record_fetcher,
    # `date` drives ordering in the bespoke fetcher; the generic last_synced_at cursor is unused
    # here because GSC's search-day column lags wall clock (see module docstring).
    partition_field="date",
    fields=GSC_FIELDS,
    where_clause=OPPORTUNITY_WHERE_CLAUSE,
    max_records=200,
    first_sync_lookback_days=GSC_LOOKBACK_DAYS,
    # The where clause is a deterministic, high-precision actionability filter, and descriptions are
    # short and self-authored, so no LLM actionability/summarization pass is needed.
)
