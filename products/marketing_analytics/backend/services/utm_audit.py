from datetime import datetime

from posthog.schema import DateRange, NativeMarketingSource

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY, Team

from products.marketing_analytics.backend.hogql_queries.adapters.base import QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.constants import INTEGRATION_PRIMARY_SOURCE
from products.marketing_analytics.backend.services.types import (
    Campaign,
    CampaignAuditResult,
    MatchType,
    TeamMappings,
    UtmAuditResponse,
    UtmEvent,
    UtmIssue,
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
        # Find the primary source for this integration
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

    # Load team mappings for source and campaign name resolution
    mappings = _load_team_mappings(team)

    # Get campaigns with spend from all integrations
    campaigns = _get_campaigns_with_spend(team, date_range)

    # Get UTM events from PostHog
    utm_events = _get_utm_events(team, date_range)

    # Cross-reference and build audit results
    results = _cross_reference(campaigns, utm_events, mappings) if campaigns else []
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
        # Add aliases (mapped)
        for alias in mappings.campaign_aliases.get(campaign_name_lower, set()):
            if alias not in campaign_lookup:
                campaign_lookup[alias] = (campaign.campaign_name, MatchType.MAPPED)

    # Pre-compute source lookup: source_name -> match_type
    source_lookup: dict[str, str] = {}
    for campaign in campaigns:
        source_name_lower = campaign.source_name.lower().strip()
        if source_name_lower not in source_lookup:
            source_lookup[source_name_lower] = MatchType.AUTO
    # Add custom source mappings (mapped)
    for custom_source, primary_source in mappings.source_to_integration.items():
        if primary_source in source_lookup and custom_source not in source_lookup:
            source_lookup[custom_source] = MatchType.MAPPED

    result: list[UtmEvent] = []
    for (utm_campaign, utm_source), count in utm_events.items():
        # Campaign match: O(1) lookup
        campaign_entry = campaign_lookup.get(utm_campaign)
        campaign_match = campaign_entry[1] if campaign_entry else MatchType.NONE
        matched_campaign_name = campaign_entry[0] if campaign_entry else None

        # Source match: O(1) lookup (check direct, then resolved)
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

    # Sort: fully unmatched first, then partial, then fully matched
    def sort_key(e: UtmEvent) -> tuple[int, int]:
        match_score = (1 if e.campaign_match != MatchType.NONE else 0) + (1 if e.source_match != MatchType.NONE else 0)
        return (match_score, -e.event_count)

    return sorted(result, key=sort_key)


def _cross_reference(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
) -> list[CampaignAuditResult]:
    """
    Cross-reference campaigns with UTM events to find issues.
    Uses pre-computed lookups for O(C) matching instead of O(C x U).
    """
    # Pre-build lookup: utm_campaign -> list of (utm_source, count)
    utm_by_campaign: dict[str, list[tuple[str, int]]] = {}
    for (utm_campaign, utm_source), count in utm_events.items():
        utm_by_campaign.setdefault(utm_campaign, []).append((utm_source, count))

    results: list[CampaignAuditResult] = []

    for campaign in campaigns:
        campaign_name_lower = campaign.campaign_name.lower().strip()
        source_name_lower = campaign.source_name.lower().strip()
        match_value = _get_match_value(campaign, mappings)
        match_field = mappings.field_preferences.get(source_name_lower, "campaign_name")
        match_display = campaign.campaign_id if match_field == "campaign_id" else campaign.campaign_name

        # Collect all utm_campaign values that match this campaign
        matching_keys = {match_value}
        matching_keys.update(mappings.campaign_aliases.get(campaign_name_lower, set()))

        # Gather all UTM events for matching keys and count
        matching_events = (
            (utm_source, count) for key in matching_keys for utm_source, count in utm_by_campaign.get(key, [])
        )

        exact_count = 0
        campaign_only_count = 0
        for utm_source, count in matching_events:
            campaign_only_count += count
            resolved_source = _resolve_source(utm_source, mappings)
            if resolved_source == source_name_lower or utm_source == source_name_lower:
                exact_count += count

        issues: list[UtmIssue] = []

        if exact_count == 0 and campaign_only_count == 0:
            issues.append(
                UtmIssue(
                    field="utm_campaign",
                    severity=UtmIssueSeverity.ERROR,
                    message=f"No UTM events detected for '{match_display}'. "
                    f"Check your UTM parameters or create a mapping.",
                )
            )
        elif exact_count == 0 and campaign_only_count > 0:
            issues.append(
                UtmIssue(
                    field="utm_source",
                    severity=UtmIssueSeverity.WARNING,
                    message=f"Campaign '{match_display}' has {campaign_only_count} events but utm_source "
                    f"doesn't match '{campaign.source_name}'. Map the source to fix this.",
                )
            )

        has_utm_events = exact_count > 0

        results.append(
            CampaignAuditResult(
                campaign_name=campaign.campaign_name,
                campaign_id=campaign.campaign_id,
                source_name=campaign.source_name,
                spend=campaign.spend,
                clicks=campaign.clicks,
                impressions=campaign.impressions,
                has_utm_events=has_utm_events,
                event_count=exact_count,
                issues=issues,
            )
        )

    return results
