"""Shared parts of the SEO site audit emitters (record kind: search_opportunity).

Site audit tables are full-refresh snapshots: each sync replaces the table with the issues the latest
crawl found, and no row carries a creation time. The emitters read the whole snapshot with the grouped
fetcher in snapshot mode (`window_days=None`) and emit one signal per issue type per site.
The query stamps each group with `now()` as `observed_at`, and the fingerprint carries its ISO week.
The ledger then lets an issue that stays open, or comes back after a fix, emit at most once per week
instead of on every sync.
"""

import hashlib
from typing import Any

from products.signals.backend.emission._prompts import (
    SEARCH_OPPORTUNITY_ACTIONABILITY_PROMPT,
    SEARCH_OPPORTUNITY_SUMMARIZATION_PROMPT,
)
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.grouped_warehouse import week_period
from products.signals.backend.emission.registry import RecordFetcher, SignalEmitter, SignalSourceTableConfig

SOURCE_TYPE = "search_opportunity"
OBSERVED_AT = "observed_at"
OBSERVED_AT_SQL = f"now() AS {OBSERVED_AT}"


def to_count(value: Any) -> int | None:
    """A warehouse count as an int, or None when it is missing or not a number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def site_audit_source_id(kind: str, record: dict[str, Any], key_fields: tuple[str, ...]) -> str:
    fingerprint = "|".join(
        (*(clean_text(record.get(field)) for field in key_fields), week_period(record.get(OBSERVED_AT)))
    )
    return f"{kind}:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def site_audit_config(
    *,
    source_product: str,
    emitter: SignalEmitter,
    record_fetcher: RecordFetcher,
    fields: tuple[str, ...],
    where_clause: str | None = None,
) -> SignalSourceTableConfig:
    return SignalSourceTableConfig(
        source_product=source_product,
        source_type=SOURCE_TYPE,
        emitter=emitter,
        record_fetcher=record_fetcher,
        # Each issue type is emitted once a week through the ledger, because every sync reads it again.
        record_processed_outputs=True,
        # The snapshot has no event time, so the fetcher reads no window. The field names the query's stamp.
        partition_field=OBSERVED_AT,
        fields=fields,
        where_clause=where_clause,
        max_records=200,
        actionability_prompt=SEARCH_OPPORTUNITY_ACTIONABILITY_PROMPT,
        summarization_prompt=SEARCH_OPPORTUNITY_SUMMARIZATION_PROMPT,
        description_summarization_threshold_chars=2000,
    )
