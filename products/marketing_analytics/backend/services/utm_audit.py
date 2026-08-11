from dataclasses import dataclass

from django.utils import timezone

import structlog

from posthog.schema import DateRange

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY, Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.marketing_analytics.backend.hogql_queries.adapters.base import QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.services.campaign_mapping_suggester import suggest_campaign_name_mappings
from products.marketing_analytics.backend.services.native_integrations import native_for_primary_source
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
from products.marketing_analytics.backend.services.utm_matching import (
    build_campaign_lookup,
    build_known_sources,
    build_source_lookup,
    get_match_field,
    get_match_value,
    load_team_mappings,
    normalize_campaign_name,
    normalize_source_name,
    resolve_source,
)

logger = structlog.get_logger(__name__)


def run_utm_audit(
    team: Team,
    date_from: str = "-30d",
    date_to: str | None = None,
    *,
    user: User | None = None,
) -> UtmAuditResponse:
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
        now=timezone.now(),
    )

    mappings = load_team_mappings(team)
    campaigns = get_campaigns_with_spend(team, date_range, user=user)
    utm_events = get_utm_campaign_catalogue(team, date_range, user=user)

    return build_audit(campaigns, utm_events, mappings)


# The audit is sync (it reads team config through the ORM and runs HogQL inline), but the
# async services — `marketing_diagnostic`, `setup_plan` — gather it alongside coroutines.
run_utm_audit_async = database_sync_to_async(run_utm_audit)


def build_audit(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
) -> UtmAuditResponse:
    """Cross-reference already-fetched campaigns and UTM events into an audit.

    Split out of `run_utm_audit` so `setup_plan` can audit the same rows it already
    pulled for the suggesters instead of paying for both queries a second time.
    """
    known_sources = build_known_sources(mappings)

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


def get_campaigns_with_spend(team: Team, date_range: QueryDateRange, *, user: User | None = None) -> list[Campaign]:
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

    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk):
        result = execute_hogql_query(query, team, user=user)
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


def get_utm_campaign_catalogue(
    team: Team, date_range: QueryDateRange, *, user: User | None = None
) -> dict[tuple[str, str], int]:
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

    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk):
        result = execute_hogql_query(
            hogql,
            team,
            user=user,
            placeholders={
                "date_from": date_range.date_from_as_hogql(),
                "date_to": date_range.date_to_as_hogql(),
            },
        )
    utm_map: dict[tuple[str, str], int] = {}
    for row in result.results or []:
        campaign = normalize_campaign_name(row[0] or "")
        source = normalize_source_name(row[1] or "")
        count = int(row[2] or 0)
        utm_map[(campaign, source)] = count
    return utm_map


# Same reason as `run_utm_audit_async`: sync ORM and HogQL, gathered by async callers.
get_campaigns_with_spend_async = database_sync_to_async(get_campaigns_with_spend)
get_utm_campaign_catalogue_async = database_sync_to_async(get_utm_campaign_catalogue)


def _build_all_utm_events(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
) -> list[UtmEvent]:
    """
    Build a list of all UTM events with their match status against campaigns.
    Uses pre-computed lookup dicts for O(1) matching per UTM event instead of O(C).
    """
    campaign_lookup = build_campaign_lookup(campaigns, mappings)
    source_lookup = build_source_lookup(campaigns, mappings)

    result: list[UtmEvent] = []
    for (utm_campaign, utm_source), count in utm_events.items():
        campaign_entry = campaign_lookup.get(utm_campaign)
        campaign_match = campaign_entry.match_type if campaign_entry else MatchType.NONE
        matched_campaign_name = campaign_entry.campaign_name if campaign_entry else None

        source_match = source_lookup.get(utm_source, MatchType.NONE)
        if source_match == MatchType.NONE:
            resolved = resolve_source(utm_source, mappings)
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
    # Events matching the campaign name but carrying no utm_source (empty/missing).
    missing_source_count: int


def _compute_campaign_stats(
    campaign: Campaign,
    utm_by_campaign: dict[str, list[tuple[str, int]]],
    mappings: TeamMappings,
) -> _CampaignStats:
    """Aggregate UTM events for a campaign and separate exact-source vs alternative-source counts."""
    campaign_name_lower = normalize_campaign_name(campaign.campaign_name)
    source_name_lower = normalize_source_name(campaign.source_name)
    match_value = get_match_value(campaign, mappings)
    match_field = get_match_field(campaign.source_name, mappings)
    match_display = campaign.campaign_id if match_field == "campaign_id" else campaign.campaign_name

    matching_keys = {match_value}
    matching_keys.update(mappings.campaign_aliases.get(campaign_name_lower, set()))

    source_counts: dict[str, int] = {}
    for key in matching_keys:
        for utm_source, count in utm_by_campaign.get(key, []):
            source_counts[utm_source] = source_counts.get(utm_source, 0) + count

    exact_count = 0
    missing_source_count = 0
    alt_source_counts: dict[str, int] = {}
    for utm_source, count in source_counts.items():
        if not utm_source:
            missing_source_count += count
            continue
        resolved_source = resolve_source(utm_source, mappings)
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
        missing_source_count=missing_source_count,
    )


_NO_TAGGED_EVENTS_HEADLINE = "No events tagged with utm_source='{platform}'"
_FALLBACK_HEADLINE = "UTM tagging issue on '{campaign}'"

_HEADLINE_BY_KIND: dict[UtmIssueKind, str] = {
    UtmIssueKind.NOT_LINKED: "No pageview events found for '{campaign}'",
    UtmIssueKind.NAME_COLLISION: "Campaign name also used on {shared}",
    UtmIssueKind.NO_TAGGED_EVENTS: _NO_TAGGED_EVENTS_HEADLINE,
    UtmIssueKind.UNKNOWN_SOURCE: _NO_TAGGED_EVENTS_HEADLINE,
    UtmIssueKind.MISSING_SOURCE: "Pageviews for '{campaign}' have no utm_source set",
}


def _make_headline(kind: UtmIssueKind, platform: str, campaign: str, shared_with_sorted: list[str]) -> str:
    """Short headline used for logs and as a fallback when the frontend doesn't render its own.

    The UI composes richer text from the structured `UtmIssue` fields (kind, alternative_sources,
    shared_with_integrations, suggested_actions) — this string is intentionally one line.

    Unknown kinds fall back rather than raising: this is a cosmetic log/fallback string, and a
    newly added `UtmIssueKind` should never be able to break the whole audit response.
    """
    template = _HEADLINE_BY_KIND.get(kind, _FALLBACK_HEADLINE)
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
            missing_source_count=stats.missing_source_count,
            suggested_actions=[SuggestedAction.SWITCH_TO_ID_MATCH, SuggestedAction.FIX_PLATFORM_URLS],
        )

    # No alternative source events. Either the campaign has pageviews with no utm_source at
    # all (missing tag — common for auto-tagged campaigns) or no matching pageviews whatsoever.
    if not alternative_sources:
        if stats.missing_source_count > 0:
            return UtmIssue(
                field="utm_source",
                severity=UtmIssueSeverity.WARNING,
                kind=UtmIssueKind.MISSING_SOURCE,
                message=_make_headline(UtmIssueKind.MISSING_SOURCE, platform, stats.match_display, []),
                alternative_sources=[],
                shared_with_integrations=[],
                missing_source_count=stats.missing_source_count,
                suggested_actions=[SuggestedAction.FIX_PLATFORM_URLS],
            )
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
            missing_source_count=stats.missing_source_count,
            suggested_actions=[SuggestedAction.FIX_PLATFORM_URLS, SuggestedAction.ADD_SOURCE_MAPPING],
        )

    return UtmIssue(
        field="utm_source",
        severity=UtmIssueSeverity.WARNING,
        kind=UtmIssueKind.NO_TAGGED_EVENTS,
        message=_make_headline(UtmIssueKind.NO_TAGGED_EVENTS, platform, stats.match_display, []),
        alternative_sources=alternative_sources,
        shared_with_integrations=[],
        missing_source_count=stats.missing_source_count,
        suggested_actions=[SuggestedAction.FIX_PLATFORM_URLS],
    )


def _mapping_candidates(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
) -> dict[tuple[str, str], str]:
    """(integration, target match value) -> the orphaned `utm_campaign` the suggester maps onto it.

    Keyed by match value, not campaign name, because that is what a proposal names and what
    id-matching integrations join on. The integration is half the key because a name is unique only
    within a platform — without it, one platform's candidate explained another's unlinked campaign.

    Only confident proposals: `ambiguous` and `unresolved` are excluded by construction. Contained,
    so a broken suggester leaves every issue exactly as it was.
    """
    try:
        proposals = suggest_campaign_name_mappings(campaigns, utm_events, mappings).proposals
    except Exception:
        logger.exception("utm_audit.mapping_candidates_failed")
        return {}

    # Highest event count wins when several orphans point at one campaign.
    best: dict[tuple[str, str], str] = {}
    best_count: dict[tuple[str, str], int] = {}
    for proposal in proposals:
        key = (proposal.integration, normalize_campaign_name(proposal.clean_name))
        if proposal.event_count > best_count.get(key, -1):
            best[key] = proposal.raw_utm_campaign
            best_count[key] = proposal.event_count
    return best


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
        known_sources = build_known_sources(mappings)

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

    # The audit sees a campaign is unlinked but not why; the suggester holds the other half.
    mapping_candidates = _mapping_candidates(campaigns, utm_events, mappings)

    results: list[CampaignAuditResult] = []
    for stats in all_stats:
        all_matching_sources = exact_matches_by_name.get(stats.campaign_name_lower, set())
        shared_with = all_matching_sources - {stats.source_name_lower}

        issue = _build_issue(stats, shared_with, known_sources)
        if issue is not None and issue.kind == UtmIssueKind.NOT_LINKED:
            # Same key the proposals were bucketed under, so id-matching integrations look up
            # correctly and a shared name can't cross platforms.
            native = native_for_primary_source(stats.campaign.source_name)
            candidate = (
                mapping_candidates.get((native.value, get_match_value(stats.campaign, mappings)))
                if native is not None
                else None
            )
            if candidate:
                issue.mapping_candidate = candidate
                # Appended: the order is the recommendation order, and the URL fix is the cure.
                issue.suggested_actions.append(SuggestedAction.ADD_CAMPAIGN_NAME_MAPPING)
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
