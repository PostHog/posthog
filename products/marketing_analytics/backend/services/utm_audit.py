from dataclasses import dataclass
from datetime import datetime

from posthog.schema import DateRange, NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY, Team

from products.marketing_analytics.backend.hogql_queries.adapters.base import QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.constants import (
    INTEGRATION_DEFAULT_SOURCES,
    INTEGRATION_PRIMARY_SOURCE,
)
from products.marketing_analytics.backend.services.types import (
    AlternativeSource,
    Campaign,
    CampaignAuditResult,
    MatchType,
    SuggestedAction,
    TeamMappings,
    UtmAuditResponse,
    UtmEvent,
    UtmIssue,
    UtmIssueKind,
    UtmIssueSeverity,
)


def _load_team_mappings(team: Team) -> TeamMappings:
    """Load custom source mappings and campaign name mappings from team config."""
    config = team.marketing_analytics_config
    if config is None:
        return TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})

    # Build source mapping: custom utm_source values -> the integration's primary source
    # e.g. custom_source_mappings = {"GoogleAds": ["partner_blog", "affiliate"]}
    # The adapter for GoogleAds uses "google" as source_name, so "partner_blog" should match "google"
    source_to_integration: dict[str, str] = {}

    custom_source_mappings = config.custom_source_mappings or {}
    for integration_type, custom_sources in custom_source_mappings.items():
        try:
            native_source = NativeMarketingSource(integration_type)
        except ValueError:
            native_source = None
        primary_source = (
            INTEGRATION_PRIMARY_SOURCE.get(native_source, integration_type.lower())
            if native_source
            else integration_type.lower()
        )
        for custom_source in custom_sources:
            source_to_integration[custom_source.lower().strip()] = primary_source.lower().strip()

    # Build campaign aliases: clean_campaign_name -> set of raw utm values
    # e.g. campaign_name_mappings = {"GoogleAds": {"brand_campaign": ["partner_q1", "brand_q1"]}}
    campaign_aliases: dict[str, set[str]] = {}
    campaign_name_mappings = config.campaign_name_mappings or {}
    for _integration_type, campaign_map in campaign_name_mappings.items():
        for clean_name, raw_values in campaign_map.items():
            clean_lower = clean_name.lower().strip()
            if clean_lower not in campaign_aliases:
                campaign_aliases[clean_lower] = set()
            for raw_value in raw_values:
                campaign_aliases[clean_lower].add(raw_value.lower().strip())

    # Build field preferences: lowercase source_name -> match field
    # Reverse map: primary_source ("google") -> integration_type ("GoogleAds")
    primary_to_integration: dict[str, str] = {}
    for native_source in NativeMarketingSource:
        primary = INTEGRATION_PRIMARY_SOURCE.get(native_source)
        if primary:
            primary_to_integration[str(primary).lower().strip()] = native_source.value

    field_preferences: dict[str, str] = {}
    campaign_field_prefs = config.campaign_field_preferences or {}
    for integration_type, prefs in campaign_field_prefs.items():
        match_field = prefs.get("match_field", "campaign_name")
        try:
            native_source = NativeMarketingSource(integration_type)
            primary = INTEGRATION_PRIMARY_SOURCE.get(native_source)
            if primary:
                field_preferences[str(primary).lower().strip()] = match_field
        except ValueError:
            pass

    return TeamMappings(
        source_to_integration=source_to_integration,
        campaign_aliases=campaign_aliases,
        field_preferences=field_preferences,
    )


def _build_known_sources(mappings: TeamMappings) -> set[str]:
    """Build the set of utm_source values claimed by any integration (default or custom).

    Used to decide whether an unmatched utm_source is safe to suggest as a mapping —
    if it's already claimed by another integration, mapping it would break that one.
    """
    known: set[str] = set()
    for sources in INTEGRATION_DEFAULT_SOURCES.values():
        for source in sources:
            known.add(source.lower().strip())
    # Custom mappings already flattened to source -> primary_source
    known.update(mappings.source_to_integration.keys())
    return known


def run_utm_audit(team: Team, date_from: str = "-30d", date_to: str | None = None) -> UtmAuditResponse:
    """
    Run a UTM audit for all marketing integrations.

    Compares campaigns with spend from ad platforms against pageview events
    with UTM parameters in PostHog to identify campaigns that are spending
    money but not properly tracked via UTMs.
    """
    date_range = QueryDateRange(
        date_range=DateRange(date_from=date_from, date_to=date_to),
        team=team,
        interval=None,
        now=datetime.now(),
    )

    mappings = _load_team_mappings(team)
    known_sources = _build_known_sources(mappings)

    campaigns = _get_campaigns_with_spend(team, date_range)
    utm_events = _get_utm_events(team, date_range)

    results = _cross_reference(campaigns, utm_events, mappings, known_sources) if campaigns else []
    all_utm = _build_all_utm_events(campaigns, utm_events, mappings)

    campaigns_with_issues = [r for r in results if len(r.issues) > 0]

    return UtmAuditResponse(
        total_campaigns=len(results),
        campaigns_with_issues=len(campaigns_with_issues),
        campaigns_without_issues=len(results) - len(campaigns_with_issues),
        total_spend_at_risk=sum(r.spend for r in campaigns_with_issues),
        results=sorted(results, key=lambda r: (-len(r.issues), -r.spend)),
        all_utm_events=all_utm,
    )


def _get_campaigns_with_spend(team: Team, date_range: QueryDateRange) -> list[Campaign]:
    """Get all campaigns with spend from marketing integrations."""
    context = QueryContext(
        date_range=date_range,
        team=team,
        base_currency=team.base_currency or DEFAULT_CURRENCY,
    )

    factory = MarketingSourceFactory(context=context)
    adapters = factory.create_adapters()
    valid_adapters = factory.get_valid_adapters(adapters)

    if not valid_adapters:
        return []

    union_subquery = factory.build_union_query_ast(valid_adapters)

    def _sum_to_float(column: str) -> ast.Call:
        return ast.Call(
            name="sum",
            args=[
                ast.Call(
                    name="toFloat",
                    args=[
                        ast.Call(
                            name="ifNull",
                            args=[ast.Field(chain=[column]), ast.Constant(value=0)],
                        )
                    ],
                )
            ],
        )

    campaign_field = ast.Field(chain=["campaign"])
    id_field = ast.Field(chain=["id"])
    source_field = ast.Field(chain=["source"])
    total_cost_field = ast.Field(chain=["total_cost"])

    # The subquery produces columns: match_key, campaign, id, source, impressions, clicks,
    # cost, reported_conversion, reported_conversion_value.
    query = ast.SelectQuery(
        select=[
            campaign_field,
            id_field,
            source_field,
            ast.Alias(alias="total_cost", expr=_sum_to_float("cost")),
            ast.Alias(alias="total_clicks", expr=_sum_to_float("clicks")),
            ast.Alias(alias="total_impressions", expr=_sum_to_float("impressions")),
        ],
        select_from=ast.JoinExpr(table=union_subquery),
        group_by=[campaign_field, id_field, source_field],
        having=ast.CompareOperation(
            left=total_cost_field,
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value=0),
        ),
        order_by=[ast.OrderExpr(expr=total_cost_field, order="DESC")],
        limit=ast.Constant(value=500),
    )

    result = execute_hogql_query(query, team)
    campaigns = []
    for row in result.results or []:
        campaigns.append(
            Campaign(
                campaign_name=row[0] or "",
                campaign_id=row[1] or "",
                source_name=row[2] or "",
                spend=float(row[3] or 0),
                clicks=int(row[4] or 0),
                impressions=int(row[5] or 0),
            )
        )
    return campaigns


def _get_utm_events(team: Team, date_range: QueryDateRange) -> dict[tuple[str, str], int]:
    """
    Get distinct utm_campaign + utm_source combinations from pageview events.
    Returns a dict mapping (campaign, source) -> event_count.
    """
    hogql = """
        SELECT
            properties.utm_campaign as utm_campaign,
            properties.utm_source as utm_source,
            count() as event_count
        FROM events
        WHERE
            event = '$pageview'
            AND timestamp >= {date_from}
            AND timestamp <= {date_to}
            AND properties.utm_campaign IS NOT NULL
            AND properties.utm_campaign != ''
        GROUP BY utm_campaign, utm_source
        ORDER BY event_count DESC
        LIMIT 5000
    """

    result = execute_hogql_query(
        hogql,
        team,
        placeholders={
            "date_from": date_range.date_from_as_hogql(),
            "date_to": date_range.date_to_as_hogql(),
        },
    )
    utm_map: dict[tuple[str, str], int] = {}
    for row in result.results or []:
        campaign = (row[0] or "").lower().strip()
        source = (row[1] or "").lower().strip()
        count = int(row[2] or 0)
        utm_map[(campaign, source)] = count
    return utm_map


def _resolve_source(utm_source: str, mappings: TeamMappings) -> str:
    """Resolve a utm_source to its integration source using custom mappings."""
    return mappings.source_to_integration.get(utm_source, utm_source)


def _get_match_value(campaign: Campaign, mappings: TeamMappings) -> str:
    """Get the campaign value to match against utm_campaign, based on field preference."""
    source_name_lower = campaign.source_name.lower().strip()
    match_field = mappings.field_preferences.get(source_name_lower, "campaign_name")
    if match_field == "campaign_id":
        return campaign.campaign_id.lower().strip()
    return campaign.campaign_name.lower().strip()


def _build_all_utm_events(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
) -> list[UtmEvent]:
    """
    Build a list of all UTM events with their match status against campaigns.
    Uses pre-computed lookup dicts for O(1) matching per UTM event instead of O(C).
    """
    # Pre-compute campaign lookup: match_value -> (campaign_name, match_type="auto")
    # and alias lookup: alias -> (campaign_name, match_type="mapped")
    campaign_lookup: dict[str, tuple[str, str]] = {}
    for campaign in campaigns:
        match_value = _get_match_value(campaign, mappings)
        campaign_name_lower = campaign.campaign_name.lower().strip()
        if match_value not in campaign_lookup:
            campaign_lookup[match_value] = (campaign.campaign_name, MatchType.AUTO)
        for alias in mappings.campaign_aliases.get(campaign_name_lower, set()):
            if alias not in campaign_lookup:
                campaign_lookup[alias] = (campaign.campaign_name, MatchType.MAPPED)

    # Pre-compute source lookup: source_name -> match_type
    source_lookup: dict[str, str] = {}
    for campaign in campaigns:
        source_name_lower = campaign.source_name.lower().strip()
        if source_name_lower not in source_lookup:
            source_lookup[source_name_lower] = MatchType.AUTO
    for custom_source, primary_source in mappings.source_to_integration.items():
        if primary_source in source_lookup and custom_source not in source_lookup:
            source_lookup[custom_source] = MatchType.MAPPED

    result: list[UtmEvent] = []
    for (utm_campaign, utm_source), count in utm_events.items():
        campaign_entry = campaign_lookup.get(utm_campaign)
        campaign_match = campaign_entry[1] if campaign_entry else MatchType.NONE
        matched_campaign_name = campaign_entry[0] if campaign_entry else None

        source_match = source_lookup.get(utm_source, MatchType.NONE)
        if source_match == MatchType.NONE:
            resolved = _resolve_source(utm_source, mappings)
            if resolved in source_lookup:
                source_match = MatchType.MAPPED if utm_source in mappings.source_to_integration else MatchType.AUTO

        result.append(
            UtmEvent(
                utm_campaign=utm_campaign,
                utm_source=utm_source,
                event_count=count,
                campaign_match=campaign_match,
                source_match=source_match,
                matched_campaign=matched_campaign_name,
            )
        )

    def sort_key(e: UtmEvent) -> tuple[int, int]:
        match_score = (1 if e.campaign_match != MatchType.NONE else 0) + (1 if e.source_match != MatchType.NONE else 0)
        return (match_score, -e.event_count)

    return sorted(result, key=sort_key)


@dataclass
class _CampaignStats:
    """Per-campaign computed stats used in the second pass of the audit."""

    campaign: Campaign
    campaign_name_lower: str
    source_name_lower: str
    match_display: str
    exact_count: int
    alt_source_counts: dict[str, int]


def _compute_campaign_stats(
    campaign: Campaign,
    utm_by_campaign: dict[str, list[tuple[str, int]]],
    mappings: TeamMappings,
) -> _CampaignStats:
    """Aggregate UTM events for a campaign and separate exact-source vs alternative-source counts."""
    campaign_name_lower = campaign.campaign_name.lower().strip()
    source_name_lower = campaign.source_name.lower().strip()
    match_value = _get_match_value(campaign, mappings)
    match_field = mappings.field_preferences.get(source_name_lower, "campaign_name")
    match_display = campaign.campaign_id if match_field == "campaign_id" else campaign.campaign_name

    matching_keys = {match_value}
    matching_keys.update(mappings.campaign_aliases.get(campaign_name_lower, set()))

    source_counts: dict[str, int] = {}
    for key in matching_keys:
        for utm_source, count in utm_by_campaign.get(key, []):
            source_counts[utm_source] = source_counts.get(utm_source, 0) + count

    exact_count = 0
    alt_source_counts: dict[str, int] = {}
    for utm_source, count in source_counts.items():
        resolved_source = _resolve_source(utm_source, mappings)
        if resolved_source == source_name_lower or utm_source == source_name_lower:
            exact_count += count
        else:
            alt_source_counts[utm_source] = count

    return _CampaignStats(
        campaign=campaign,
        campaign_name_lower=campaign_name_lower,
        source_name_lower=source_name_lower,
        match_display=match_display,
        exact_count=exact_count,
        alt_source_counts=alt_source_counts,
    )


_NO_TAGGED_EVENTS_HEADLINE = "No events tagged with utm_source='{platform}'"

_HEADLINE_BY_KIND: dict[UtmIssueKind, str] = {
    UtmIssueKind.NOT_LINKED: "No pageview events found for '{campaign}'",
    UtmIssueKind.NAME_COLLISION: "Campaign name also used on {shared}",
    UtmIssueKind.NO_TAGGED_EVENTS: _NO_TAGGED_EVENTS_HEADLINE,
    UtmIssueKind.UNKNOWN_SOURCE: _NO_TAGGED_EVENTS_HEADLINE,
}


def _make_headline(kind: UtmIssueKind, platform: str, campaign: str, shared_with_sorted: list[str]) -> str:
    """Short headline used for logs and as a fallback when the frontend doesn't render its own.

    The UI composes richer text from the structured `UtmIssue` fields (kind, alternative_sources,
    shared_with_integrations, suggested_actions) — this string is intentionally one line.
    """
    template = _HEADLINE_BY_KIND[kind]
    return template.format(
        platform=platform,
        campaign=campaign,
        shared=", ".join(shared_with_sorted) or "another integration",
    )


def _build_issue(
    stats: _CampaignStats,
    shared_with: set[str],
    known_sources: set[str],
) -> UtmIssue | None:
    """Given a campaign's stats, return the single audit issue to surface (or None if OK)."""
    if stats.exact_count > 0:
        return None

    alt_sources_sorted = sorted(stats.alt_source_counts.items(), key=lambda item: -item[1])
    alternative_sources = [AlternativeSource(utm_source=s, event_count=c) for s, c in alt_sources_sorted]
    shared_with_sorted = sorted(shared_with)
    platform = stats.source_name_lower

    # Name collision trumps everything: another integration already matches this name.
    # Primary fix: switch to campaign_id matching so the audit can tell the platforms apart.
    # Secondary: fix the platform URLs to include the expected utm_source.
    if shared_with:
        return UtmIssue(
            field="utm_source" if alternative_sources else "utm_campaign",
            severity=UtmIssueSeverity.WARNING,
            kind=UtmIssueKind.NAME_COLLISION,
            message=_make_headline(UtmIssueKind.NAME_COLLISION, platform, stats.match_display, shared_with_sorted),
            alternative_sources=alternative_sources,
            shared_with_integrations=shared_with_sorted,
            suggested_actions=[SuggestedAction.SWITCH_TO_ID_MATCH, SuggestedAction.FIX_PLATFORM_URLS],
        )

    # No events at all, and no other integration claims this name → just fix the URLs.
    if not alternative_sources:
        return UtmIssue(
            field="utm_campaign",
            severity=UtmIssueSeverity.ERROR,
            kind=UtmIssueKind.NOT_LINKED,
            message=_make_headline(UtmIssueKind.NOT_LINKED, platform, stats.match_display, []),
            alternative_sources=[],
            shared_with_integrations=[],
            suggested_actions=[SuggestedAction.FIX_PLATFORM_URLS],
        )

    # Has events but with wrong source. If every alt_source is already claimed by another
    # integration (via defaults or custom mappings), a new source mapping would hijack that
    # other integration's attribution — don't suggest it.
    any_alt_source_unknown = any(source not in known_sources for source in stats.alt_source_counts)

    if any_alt_source_unknown:
        return UtmIssue(
            field="utm_source",
            severity=UtmIssueSeverity.WARNING,
            kind=UtmIssueKind.UNKNOWN_SOURCE,
            message=_make_headline(UtmIssueKind.UNKNOWN_SOURCE, platform, stats.match_display, []),
            alternative_sources=alternative_sources,
            shared_with_integrations=[],
            suggested_actions=[SuggestedAction.FIX_PLATFORM_URLS, SuggestedAction.ADD_SOURCE_MAPPING],
        )

    return UtmIssue(
        field="utm_source",
        severity=UtmIssueSeverity.WARNING,
        kind=UtmIssueKind.NO_TAGGED_EVENTS,
        message=_make_headline(UtmIssueKind.NO_TAGGED_EVENTS, platform, stats.match_display, []),
        alternative_sources=alternative_sources,
        shared_with_integrations=[],
        suggested_actions=[SuggestedAction.FIX_PLATFORM_URLS],
    )


def _cross_reference(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
    known_sources: set[str] | None = None,
) -> list[CampaignAuditResult]:
    """
    Cross-reference campaigns with UTM events to find issues.

    Runs in two passes:
    1. Compute per-campaign exact/alt source counts and record which (name, platform) pairs
       actually match events.
    2. For each campaign, detect whether another platform matches the same name (shared name)
       and build the appropriate issue.
    """
    if known_sources is None:
        known_sources = _build_known_sources(mappings)

    utm_by_campaign: dict[str, list[tuple[str, int]]] = {}
    for (utm_campaign, utm_source), count in utm_events.items():
        utm_by_campaign.setdefault(utm_campaign, []).append((utm_source, count))

    all_stats: list[_CampaignStats] = [_compute_campaign_stats(c, utm_by_campaign, mappings) for c in campaigns]

    # Map campaign_name_lower -> set of source_name_lower with exact matches.
    # Used to detect cross-platform name collisions.
    exact_matches_by_name: dict[str, set[str]] = {}
    for stats in all_stats:
        if stats.exact_count > 0:
            exact_matches_by_name.setdefault(stats.campaign_name_lower, set()).add(stats.source_name_lower)

    results: list[CampaignAuditResult] = []
    for stats in all_stats:
        all_matching_sources = exact_matches_by_name.get(stats.campaign_name_lower, set())
        shared_with = all_matching_sources - {stats.source_name_lower}

        issue = _build_issue(stats, shared_with, known_sources)
        issues = [issue] if issue is not None else []

        results.append(
            CampaignAuditResult(
                campaign_name=stats.campaign.campaign_name,
                campaign_id=stats.campaign.campaign_id,
                source_name=stats.campaign.source_name,
                spend=stats.campaign.spend,
                clicks=stats.campaign.clicks,
                impressions=stats.campaign.impressions,
                has_utm_events=stats.exact_count > 0,
                event_count=stats.exact_count,
                issues=issues,
            )
        )

    return results
