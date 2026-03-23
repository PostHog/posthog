from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import structlog

from posthog.schema import DateRange

from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY, Team

from products.marketing_analytics.backend.hogql_queries.adapters.base import QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory

logger = structlog.get_logger(__name__)


class UtmIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class UtmIssue:
    field: str
    severity: UtmIssueSeverity
    message: str


@dataclass
class CampaignAuditResult:
    campaign_name: str
    campaign_id: str
    source_name: str
    source_type: str
    spend: float
    clicks: int
    impressions: int
    has_utm_events: bool
    event_count: int
    issues: list[UtmIssue] = field(default_factory=list)


@dataclass
class UtmAuditResponse:
    total_campaigns: int
    campaigns_with_issues: int
    campaigns_without_issues: int
    total_spend_at_risk: float
    results: list[CampaignAuditResult]


def run_utm_audit(team: Team, date_from: str = "-30d", date_to: str | None = None) -> UtmAuditResponse:
    """
    Run a UTM audit for all marketing integrations.

    Compares campaigns with spend from ad platforms against pageview events
    with UTM parameters in PostHog to identify campaigns that are spending
    money but not properly tracked via UTMs.
    """
    # Get campaigns with spend from all integrations
    campaigns = _get_campaigns_with_spend(team, date_from, date_to)
    if not campaigns:
        return UtmAuditResponse(
            total_campaigns=0,
            campaigns_with_issues=0,
            campaigns_without_issues=0,
            total_spend_at_risk=0,
            results=[],
        )

    # Get UTM events from PostHog
    utm_events = _get_utm_events(team, date_from, date_to)

    # Cross-reference and build audit results
    results = _cross_reference(campaigns, utm_events)

    campaigns_with_issues = [r for r in results if len(r.issues) > 0]

    return UtmAuditResponse(
        total_campaigns=len(results),
        campaigns_with_issues=len(campaigns_with_issues),
        campaigns_without_issues=len(results) - len(campaigns_with_issues),
        total_spend_at_risk=sum(r.spend for r in campaigns_with_issues),
        results=sorted(results, key=lambda r: (-len(r.issues), -r.spend)),
    )


def _get_campaigns_with_spend(team: Team, date_from: str, date_to: str | None) -> list[dict[str, Any]]:
    """Get all campaigns with spend from marketing integrations."""
    date_range = QueryDateRange(
        date_range=DateRange(date_from=date_from, date_to=date_to),
        team=team,
        interval=None,
        now=datetime.now(),
    )

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

    union_query = factory.build_union_query(valid_adapters)
    if not union_query:
        return []

    # Query campaigns grouped by campaign_name, source_name with aggregated spend
    hogql = f"""
        SELECT
            campaign_name,
            campaign_id,
            source_name,
            sum(toFloat(ifNull(cost, 0))) as total_cost,
            sum(toFloat(ifNull(clicks, 0))) as total_clicks,
            sum(toFloat(ifNull(impressions, 0))) as total_impressions
        FROM ({union_query})
        GROUP BY campaign_name, campaign_id, source_name
        HAVING total_cost > 0
        ORDER BY total_cost DESC
        LIMIT 500
    """

    try:
        result = execute_hogql_query(hogql, team)
        campaigns = []
        for row in result.results or []:
            campaigns.append(
                {
                    "campaign_name": row[0] or "",
                    "campaign_id": row[1] or "",
                    "source_name": row[2] or "",
                    "spend": float(row[3] or 0),
                    "clicks": int(row[4] or 0),
                    "impressions": int(row[5] or 0),
                }
            )
        return campaigns
    except Exception as e:
        logger.exception("Failed to get campaigns with spend", error=str(e))
        return []


def _get_utm_events(team: Team, date_from: str, date_to: str | None) -> dict[tuple[str, str], int]:
    """
    Get distinct utm_campaign + utm_source combinations from pageview events.
    Returns a dict mapping (campaign, source) -> event_count.
    """
    date_to_clause = f"AND timestamp <= toDateTime('{date_to}')" if date_to else ""

    hogql = f"""
        SELECT
            properties.$utm_campaign as utm_campaign,
            properties.$utm_source as utm_source,
            count() as event_count
        FROM events
        WHERE
            event = '$pageview'
            AND timestamp >= toDateTime('{date_from}')
            {date_to_clause}
            AND properties.$utm_campaign IS NOT NULL
            AND properties.$utm_campaign != ''
        GROUP BY utm_campaign, utm_source
    """

    try:
        result = execute_hogql_query(hogql, team)
        utm_map: dict[tuple[str, str], int] = {}
        for row in result.results or []:
            campaign = (row[0] or "").lower().strip()
            source = (row[1] or "").lower().strip()
            count = int(row[2] or 0)
            utm_map[(campaign, source)] = count
        return utm_map
    except Exception as e:
        logger.exception("Failed to get UTM events", error=str(e))
        return {}


def _cross_reference(
    campaigns: list[dict[str, Any]],
    utm_events: dict[tuple[str, str], int],
) -> list[CampaignAuditResult]:
    """
    Cross-reference campaigns with UTM events to find issues.
    Uses case-insensitive matching.
    """
    results: list[CampaignAuditResult] = []

    for campaign in campaigns:
        campaign_name = campaign["campaign_name"]
        source_name = campaign["source_name"]
        campaign_name_lower = campaign_name.lower().strip()
        source_name_lower = source_name.lower().strip()

        # Try exact match (campaign + source)
        exact_key = (campaign_name_lower, source_name_lower)
        event_count = utm_events.get(exact_key, 0)

        # Try campaign-only match (any source)
        campaign_only_count = sum(count for (c, _), count in utm_events.items() if c == campaign_name_lower)

        issues: list[UtmIssue] = []

        if event_count == 0 and campaign_only_count == 0:
            # No UTM events at all for this campaign
            issues.append(
                UtmIssue(
                    field="utm_campaign",
                    severity=UtmIssueSeverity.ERROR,
                    message=f"No pageview events found with utm_campaign matching '{campaign_name}'. "
                    f"This campaign is spending ${campaign['spend']:.2f} but has no UTM tracking.",
                )
            )
        elif event_count == 0 and campaign_only_count > 0:
            # Campaign exists but source doesn't match
            issues.append(
                UtmIssue(
                    field="utm_source",
                    severity=UtmIssueSeverity.WARNING,
                    message=f"Campaign '{campaign_name}' has {campaign_only_count} events but none with "
                    f"utm_source='{source_name}'. The utm_source may be misconfigured.",
                )
            )

        has_utm_events = event_count > 0

        results.append(
            CampaignAuditResult(
                campaign_name=campaign_name,
                campaign_id=campaign["campaign_id"],
                source_name=source_name,
                source_type=source_name,
                spend=campaign["spend"],
                clicks=campaign["clicks"],
                impressions=campaign["impressions"],
                has_utm_events=has_utm_events,
                event_count=event_count,
                issues=issues,
            )
        )

    return results
