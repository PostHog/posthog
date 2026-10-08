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
from asgiref.sync import sync_to_async

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.marketing_analytics.backend.services.native_integrations import (
    NATIVE_TO_KEY,
    NativeIntegration,
    build_combined_alias_map,
    display_name_for_key,
    get_enabled_native_integrations,
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


@frozen
class AttributionHealthEntry:
    integration_key: NativeIntegration
    display_name: str
    events_with_utm_last_7d: int
    events_matched_last_7d: int
    events_unmatched_likely_yours_last_7d: int
    last_event_with_matching_utm_at: datetime | None
    matched_pct: float
    sample_unmatched_utm_sources: list[UnmatchedUtmSample] = field(default_factory=list)
    # Of the matched events, how many look paid, and how many carry any utm_medium.
    # Missing paid signals mean unknown intent, not necessarily organic traffic.
    events_matched_paid_last_7d: int = 0
    events_matched_tagged_medium_last_7d: int = 0


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

    enabled_integrations = await sync_to_async(get_enabled_native_integrations, thread_sensitive=False)(team)
    targets = [NATIVE_TO_KEY[native] for native in enabled_integrations.values()]
    enabled_keys = set(targets)
    alias_map = {alias: key for alias, key in alias_map.items() if key in enabled_keys}
    if source_type is not None:
        native = enabled_integrations.get(source_type)
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
                acc.paid_count += row.platform_paid_event_counts.get(matched_key, row.paid_event_count)
                acc.tagged_medium_count += row.tagged_medium_count
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


@frozen
class _UtmRow:
    raw_utm_source: str
    event_count: int
    last_seen_at: datetime | None
    # A cost-bearing utm_medium, per PostHog's own channel-type rule
    # (posthog.com/docs/data/channel-type). Platform-agnostic: any source can be paid.
    paid_event_count: int = 0
    # Each platform count is the union of paid medium and its own ad signals.
    platform_paid_event_counts: dict[NativeIntegration, int] = field(default_factory=dict)
    # Events carrying any utm_medium at all. Separates "tagged, and organic" from
    # "not tagged", which are different answers to "is this paid?".
    tagged_medium_count: int = 0


# Mutable by design: one instance per integration, summed across the utm rows.
@dataclass(frozen=False)
class _IntegrationAccumulator:
    key: NativeIntegration
    matched_count: int = 0
    paid_count: int = 0
    tagged_medium_count: int = 0
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
            events_matched_paid_last_7d=self.paid_count,
            events_matched_tagged_medium_last_7d=self.tagged_medium_count,
        )


@database_sync_to_async
def _build_team_alias_map(team: Team) -> dict[str, NativeIntegration]:
    """Merge canonical aliases with the team's `custom_source_mappings` so user
    overrides are honored when classifying utm_source values."""
    config = getattr(team, "marketing_analytics_config", None)
    custom = config.custom_source_mappings if config is not None else {}
    return build_combined_alias_map(custom)


# These identify ad interactions; fbclid and epik can also accompany unpaid visits.
_PLATFORM_AD_PARAMETERS: dict[NativeIntegration, tuple[str, ...]] = {
    "google_ads": ("gclid", "gbraid", "wbraid", "gad_source", "gad_campaignid"),
    "openai_ads": ("oppref",),
    "bing_ads": ("msclkid",),
    "linkedin_ads": ("li_fat_id",),
    "reddit_ads": ("rdt_cid",),
    "snapchat_ads": ("ScCid", "sccid"),
    "tiktok_ads": ("ttclid",),
    "rokt_ads": ("rtid",),
}


def _event_parameter_matches(parameter: str, value: str | None = None) -> ast.Expr:
    # SDKs do not capture every platform's parameter as an event property.
    property_value = parse_expr(
        "trim(ifNull(toString({property}), ''))",
        placeholders={"property": ast.Field(chain=["properties", parameter])},
    )
    url_value = parse_expr(
        "trim(decodeURLComponent(extractURLParameter(ifNull(properties.$current_url, ''), {parameter})))",
        placeholders={"parameter": ast.Constant(value=parameter)},
    )
    return ast.Or(
        exprs=[
            parse_expr(
                "{candidate} != ''" if value is None else "{candidate} = {value}",
                placeholders={"candidate": candidate, "value": ast.Constant(value=value)},
            )
            for candidate in (property_value, url_value)
        ]
    )


def _platform_paid_expressions(paid_medium: ast.Expr) -> dict[NativeIntegration, ast.Expr]:
    expressions: dict[NativeIntegration, ast.Expr] = {
        key: ast.Or(exprs=[paid_medium, *[_event_parameter_matches(parameter) for parameter in parameters]])
        for key, parameters in _PLATFORM_AD_PARAMETERS.items()
    }
    # Saved ads retain campaign tags, but Pinterest marks their unpaid clicks pp=1.
    expressions["pinterest_ads"] = parse_expr(
        "({paid_medium} OR {paid_click}) AND NOT {earned_click}",
        placeholders={
            "paid_medium": paid_medium,
            "paid_click": _event_parameter_matches("pp", "0"),
            "earned_click": _event_parameter_matches("pp", "1"),
        },
    )
    return expressions


@database_sync_to_async
def _fetch_utm_groups(team: Team, *, lookback_days: int) -> list[_UtmRow]:
    """HogQL aggregation of utm_source counts and latest timestamp within the window.

    Intentionally not restricted to `$pageview` — conversion goals are often custom
    events, so attribution should reflect all UTM-tagged activity.

    The window ends at the run time. Event timestamps come from the client, so a device
    with a wrong clock can stamp an event years ahead and make `max(timestamp)` report a
    last-seen date in the future.
    """
    now = timezone.now()
    since = now - timedelta(days=lookback_days)
    paid_medium = parse_expr(
        """
        lower(trim(properties.utm_medium)) IN ('cpc', 'cpm', 'cpv', 'cpa', 'ppc', 'retargeting')
        OR startsWith(lower(trim(properties.utm_medium)), 'paid')
        """
    )
    platform_paid = _platform_paid_expressions(paid_medium)
    query = parse_select(
        """
        SELECT
            lower(trim(properties.utm_source)) AS raw_utm_source,
            count() AS event_count,
            max(timestamp) AS last_seen_at,
            countIf({paid_medium}) AS paid_event_count,
            countIf(properties.utm_medium IS NOT NULL AND trim(properties.utm_medium) != '') AS tagged_medium_count
        FROM events
        WHERE
            timestamp >= {since}
            AND timestamp <= {until}
            AND properties.utm_source IS NOT NULL
            AND properties.utm_source != ''
        GROUP BY raw_utm_source
        ORDER BY event_count DESC
        LIMIT {limit}
    """,
        placeholders={
            "paid_medium": paid_medium,
            "since": ast.Constant(value=since),
            "until": ast.Constant(value=now),
            "limit": ast.Constant(value=HOGQL_GROUP_LIMIT),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    query.select.extend(ast.Call(name="countIf", args=[expression]) for expression in platform_paid.values())
    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk):
        result = execute_hogql_query(query, team)
    rows: list[_UtmRow] = []
    for row in result.results or []:
        raw, count, last_at, paid_count, tagged_count = row[:5]
        if not raw:
            continue
        rows.append(
            _UtmRow(
                raw_utm_source=cast(str, raw),
                event_count=int(count or 0),
                last_seen_at=last_at if isinstance(last_at, datetime) else None,
                paid_event_count=int(paid_count or 0),
                platform_paid_event_counts={key: int(value or 0) for key, value in zip(platform_paid, row[5:])},
                tagged_medium_count=int(tagged_count or 0),
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
