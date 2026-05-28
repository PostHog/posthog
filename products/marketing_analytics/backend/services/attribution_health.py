"""Attribution-side health: are `utm_source` events arriving and do their values
match each native integration?

The DW-sync side lives in `data_source_health`; cross-domain correlation in
`marketing_diagnostic`.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.marketing_analytics.backend.services.native_integrations import (
    EXTERNAL_SOURCE_TYPE_TO_NATIVE,
    NATIVE_TO_KEY,
    NativeIntegration,
    build_combined_alias_map,
    display_name_for_key,
    lookup_in,
    normalize,
)

logger = structlog.get_logger(__name__)

# Default lookback window. Chosen to match `utm_audit` and the Marketing
# Analytics dashboard's typical "last 7 days" view.
DEFAULT_LOOKBACK_DAYS = 7

# Cap on how many distinct utm_source values we report as samples per
# integration. Keep small — this is fed to LLMs and dashboards.
MAX_SAMPLE_UNMATCHED = 5

# Cap on how many globally-unmatched raw values we surface. Higher than
# MAX_SAMPLE_UNMATCHED because callers like `mapping_suggester` need the full
# unmatched catalogue to reason about it.
MAX_GLOBAL_UNMATCHED = 50

# Cap on how many distinct utm_source values we pull from ClickHouse, ordered
# by event count. Beyond this is long-tail typos; the response flags
# `utm_source_catalogue_truncated` when the cap is hit so callers know the
# totals are top-N subtotals rather than the full count.
HOGQL_GROUP_LIMIT = 500


@dataclass
class UnmatchedUtmSample:
    """A raw utm_source value that doesn't match any integration. `suggested_integration`
    is set when one of its tokens is a known alias (e.g. `facebook_paid` → Meta)."""

    raw_value: str
    event_count: int
    suggested_integration: NativeIntegration | None


@dataclass
class AttributionHealthEntry:
    integration_key: NativeIntegration
    display_name: str
    events_with_utm_last_7d: int
    events_matched_last_7d: int
    events_unmatched_likely_yours_last_7d: int
    last_event_with_matching_utm_at: datetime | None
    matched_pct: float
    sample_unmatched_utm_sources: list[UnmatchedUtmSample] = field(default_factory=list)


@dataclass
class UtmSourceSample:
    """Catalogue entry for a raw utm_source value (matched or not). `matched_integration`
    is an exact alias hit; `suggested_integration` is a softer token-level guess."""

    raw_value: str
    event_count: int
    matched_integration: NativeIntegration | None
    suggested_integration: NativeIntegration | None


@dataclass
class AttributionHealthResponse:
    lookback_days: int
    integrations: list[AttributionHealthEntry] = field(default_factory=list)
    total_events_with_utm: int = 0
    total_events_matched_to_any_integration: int = 0
    total_events_unmatched: int = 0
    sample_globally_unmatched: list[UnmatchedUtmSample] = field(default_factory=list)
    # Full catalogue of utm_source values seen in the window (top N by count),
    # both matched and unmatched. Lets callers answer "what utm_sources arrive
    # on this team's events?" without a separate SQL roundtrip.
    all_utm_source_samples: list[UtmSourceSample] = field(default_factory=list)
    # Distinct utm_source values among the top `HOGQL_GROUP_LIMIT` by event count.
    # When `utm_source_catalogue_truncated` is true this is a subtotal (capped at
    # HOGQL_GROUP_LIMIT), not the true distinct count.
    total_distinct_utm_sources: int = 0
    # True when the ClickHouse aggregation hit HOGQL_GROUP_LIMIT distinct
    # utm_source values: the long tail beyond that is uncounted, so
    # `total_events_with_utm` and the totals above are top-N subtotals.
    utm_source_catalogue_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def get_attribution_health(
    team: Team,
    *,
    source_type: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    custom_source_mappings: dict | None = None,
) -> AttributionHealthResponse:
    """Aggregate UTM-tagged event counts per native integration over `lookback_days`.

    `source_type` filters output to a single integration (same key as
    data_source_health); aggregate totals still reflect full team activity.
    `custom_source_mappings` lets callers pass a pre-loaded config to avoid a
    Postgres roundtrip; when None, the service loads it itself.
    """
    rows = await _fetch_utm_groups(team, lookback_days=lookback_days)
    if custom_source_mappings is None:
        alias_map = await _build_team_alias_map(team)
    else:
        alias_map = build_combined_alias_map(custom_source_mappings)

    targets = list(NATIVE_TO_KEY.values())
    if source_type is not None:
        native = EXTERNAL_SOURCE_TYPE_TO_NATIVE.get(source_type)
        targets = [NATIVE_TO_KEY[native]] if native else []

    allowed = set(targets)
    per_integration: dict[NativeIntegration, _IntegrationAccumulator] = {
        key: _IntegrationAccumulator(key=key) for key in targets
    }
    globally_unmatched: list[UnmatchedUtmSample] = []
    all_samples: list[UtmSourceSample] = []
    total_with_utm = 0
    total_matched_any = 0
    total_unmatched = 0

    for row in rows:
        raw_value: str = row.raw_utm_source
        count: int = row.event_count
        last_at: datetime | None = row.last_seen_at

        total_with_utm += count

        matched_key = lookup_in(raw_value, alias_map)
        suggestion = _suggest_integration_by_alias_token(raw_value, alias_map, allowed)
        all_samples.append(
            UtmSourceSample(
                raw_value=raw_value,
                event_count=count,
                matched_integration=matched_key,
                suggested_integration=suggestion,
            )
        )

        if matched_key is not None:
            total_matched_any += count
            acc = per_integration.get(matched_key)
            if acc is not None:
                acc.matched_count += count
                candidates = [d for d in (acc.last_matched_at, last_at) if d is not None]
                acc.last_matched_at = max(candidates) if candidates else None
            continue

        # Unmatched at the alias level.
        sample = UnmatchedUtmSample(
            raw_value=raw_value,
            event_count=count,
            suggested_integration=suggestion,
        )
        globally_unmatched.append(sample)
        total_unmatched += count
        if suggestion is not None:
            acc = per_integration[suggestion]
            acc.likely_yours_count += count
            acc.likely_yours_samples.append(sample)

    entries = [acc.to_entry(total_with_utm) for acc in per_integration.values()]
    globally_unmatched.sort(key=lambda s: s.event_count, reverse=True)
    all_samples.sort(key=lambda s: s.event_count, reverse=True)

    return AttributionHealthResponse(
        lookback_days=lookback_days,
        integrations=entries,
        total_events_with_utm=total_with_utm,
        total_events_matched_to_any_integration=total_matched_any,
        total_events_unmatched=total_unmatched,
        sample_globally_unmatched=globally_unmatched[:MAX_GLOBAL_UNMATCHED],
        all_utm_source_samples=all_samples[:MAX_GLOBAL_UNMATCHED],
        total_distinct_utm_sources=len(all_samples),
        utm_source_catalogue_truncated=len(rows) >= HOGQL_GROUP_LIMIT,
    )


@dataclass
class _UtmRow:
    raw_utm_source: str
    event_count: int
    last_seen_at: datetime | None


@dataclass
class _IntegrationAccumulator:
    key: NativeIntegration
    matched_count: int = 0
    likely_yours_count: int = 0
    last_matched_at: datetime | None = None
    likely_yours_samples: list[UnmatchedUtmSample] = field(default_factory=list)

    def to_entry(self, total_with_utm: int) -> AttributionHealthEntry:
        display = display_name_for_key(self.key)

        matched_pct = 0.0
        if total_with_utm > 0:
            matched_pct = round((self.matched_count / total_with_utm) * 100, 2)

        self.likely_yours_samples.sort(key=lambda s: s.event_count, reverse=True)
        return AttributionHealthEntry(
            integration_key=self.key,
            display_name=display,
            events_with_utm_last_7d=total_with_utm,
            events_matched_last_7d=self.matched_count,
            events_unmatched_likely_yours_last_7d=self.likely_yours_count,
            last_event_with_matching_utm_at=self.last_matched_at,
            matched_pct=matched_pct,
            sample_unmatched_utm_sources=self.likely_yours_samples[:MAX_SAMPLE_UNMATCHED],
        )


@database_sync_to_async
def _build_team_alias_map(team: Team) -> dict[str, NativeIntegration]:
    """Merge canonical aliases with the team's `custom_source_mappings` so user
    overrides are honored when classifying utm_source values."""
    config = getattr(team, "marketing_analytics_config", None)
    custom = config.custom_source_mappings if config is not None else {}
    return build_combined_alias_map(custom)


@database_sync_to_async
def _fetch_utm_groups(team: Team, *, lookback_days: int) -> list[_UtmRow]:
    """HogQL aggregation of utm_source counts and latest timestamp within the window.

    Intentionally not restricted to `$pageview` — conversion goals are often custom
    events, so attribution should reflect all UTM-tagged activity.
    """
    since = timezone.now() - timedelta(days=lookback_days)
    hogql = """
        SELECT
            lower(trim(properties.utm_source)) AS raw_utm_source,
            count() AS event_count,
            max(timestamp) AS last_seen_at
        FROM events
        WHERE
            timestamp >= {since}
            AND properties.utm_source IS NOT NULL
            AND properties.utm_source != ''
        GROUP BY raw_utm_source
        ORDER BY event_count DESC
        LIMIT {limit}
    """
    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk):
        result = execute_hogql_query(
            hogql,
            team,
            placeholders={
                "since": ast.Constant(value=since),
                "limit": ast.Constant(value=HOGQL_GROUP_LIMIT),
            },
        )
    rows: list[_UtmRow] = []
    for row in result.results or []:
        raw, count, last_at = row[0], row[1], row[2]
        if not raw:
            continue
        rows.append(
            _UtmRow(
                raw_utm_source=cast(str, raw),
                event_count=int(count or 0),
                last_seen_at=last_at if isinstance(last_at, datetime) else None,
            )
        )
    return rows


def _suggest_integration_by_alias_token(
    raw_utm_source: str, alias_map: dict[str, NativeIntegration], allowed: set[NativeIntegration]
) -> NativeIntegration | None:
    """Suggest an integration for a value that didn't match exactly, when one of
    its tokens is a known alias (canonical or team-custom) — e.g. `facebook_paid`
    → Meta via the `facebook` token.

    `allowed` scopes the result to the integrations the caller is reporting on, so
    a `source_type` filter can't yield an out-of-scope integration."""
    for token in re.split(r"[^a-z0-9]+", raw_utm_source.lower()):
        integration = alias_map.get(normalize(token))
        if integration is not None and integration in allowed:
            return integration
    return None
