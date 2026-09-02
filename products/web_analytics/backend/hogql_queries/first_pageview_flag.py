from typing import TYPE_CHECKING, Any, Optional

import structlog
import posthoganalytics

from posthog.schema import ProductKey, SessionPropertyFilter, WebStatsBreakdown

if TYPE_CHECKING:
    from posthog.models import Team

logger = structlog.get_logger(__name__)

FIRST_PAGEVIEW_ATTRIBUTION_FEATURE_FLAG = "web-analytics-first-pageview-attribution"

# Stored session properties the row-click drill-downs filter on, mapped to the
# FirstPageview* breakdown whose value expression reproduces them. Flag-on, a
# filter on one of these is rewritten to match first-pageview attribution so a
# drilled-down tile reconciles with the breakdown row that produced it.
# $entry_utm_source_medium_campaign has no entry here on purpose: the compound
# breakdown is not filterable, the UI splits a click on it into separate
# source / medium / campaign filters, each of which is remapped individually.
SESSION_PROPERTY_TO_FIRST_PAGEVIEW: dict[str, WebStatsBreakdown] = {
    "$channel_type": WebStatsBreakdown.FIRST_PAGEVIEW_CHANNEL_TYPE,
    "$entry_utm_source": WebStatsBreakdown.FIRST_PAGEVIEW_UTM_SOURCE,
    "$entry_utm_campaign": WebStatsBreakdown.FIRST_PAGEVIEW_UTM_CAMPAIGN,
    "$entry_utm_medium": WebStatsBreakdown.FIRST_PAGEVIEW_UTM_MEDIUM,
    "$entry_utm_term": WebStatsBreakdown.FIRST_PAGEVIEW_UTM_TERM,
    "$entry_utm_content": WebStatsBreakdown.FIRST_PAGEVIEW_UTM_CONTENT,
    "$entry_referring_domain": WebStatsBreakdown.FIRST_PAGEVIEW_REFERRING_DOMAIN,
}


def evaluate_team_rollout_flag(team: "Team", flag_key: str, failure_log_event: str) -> bool:
    """Evaluate a team-scoped rollout flag locally, failing closed on flag-service errors.

    A raised exception here must never fail the query: evaluation failure degrades
    to the flag-off path. For optimization flags that is merely the slower query
    shape; for result-changing flags (first-pageview attribution) it silently
    restores the old semantics, so both the exception and the None-return cases
    (local evaluation unavailable) are logged to keep a fleet-wide fallback
    visible during rollout.

    Conditions on this flag must be group conditions, never person or cohort
    ones: the distinct id passed here is a team uuid with no person behind it,
    so a person-scoped condition is unresolvable locally, returns None, and the
    flag silently evaluates to False for everyone.
    """
    try:
        enabled = posthoganalytics.feature_enabled(
            flag_key,
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if enabled is None:
            logger.warning(failure_log_event, reason="feature_enabled_returned_none", team_id=team.pk)
            return False
        return bool(enabled)
    except Exception as e:
        logger.warning(failure_log_event, error=e, team_id=team.pk)
        return False


def first_pageview_attribution_enabled(team: "Team") -> bool:
    return evaluate_team_rollout_flag(
        team, FIRST_PAGEVIEW_ATTRIBUTION_FEATURE_FLAG, "web_analytics_first_pageview_attribution_flag_failed"
    )


def rewritable_session_filters(properties: Any) -> list[SessionPropertyFilter]:
    # `properties` is a flat list on every web analytics query, but the shared
    # insight schema also allows a nested PropertyGroupFilter, which is not
    # iterable. Anything that is not a plain list is left untouched rather than
    # walked, so an unexpected shape degrades to entry attribution instead of
    # raising while the query is being built.
    if not isinstance(properties, list):
        return []
    return [
        p for p in properties if isinstance(p, SessionPropertyFilter) and p.key in SESSION_PROPERTY_TO_FIRST_PAGEVIEW
    ]


def is_web_analytics_query(query: Any) -> bool:
    """Read from the query's own tags rather than the ambient ClickHouse query
    tags because `get_cache_payload` strips `tags` before hashing, so the
    decision has to be reachable from the query object at cache-key time.
    """
    tags = getattr(query, "tags", None)
    return getattr(tags, "productKey", None) == ProductKey.WEB_ANALYTICS


def query_has_rewritable_session_filters(query: Any) -> bool:
    """Web analytics puts the scene's filters at query level on most tiles but on
    the series for the Active Hours tiles, so both levels count.
    """
    if rewritable_session_filters(getattr(query, "properties", None)):
        return True
    return any(
        rewritable_session_filters(getattr(series, "properties", None))
        for series in (getattr(query, "series", None) or [])
    )


def resolve_first_pageview_filters_modifier(query: Any, team: "Team", current: Optional[bool]) -> Optional[bool]:
    """Effective value of the `webAnalyticsFirstPageviewFilters` modifier.

    The decision has to live on the modifier because `get_cache_payload` hashes
    `hogql_modifiers`: entry-attributed and first-pageview runs of the same query
    must not share a cache entry.

    The guards run before the flag so no other query pays a flag-service call.
    """
    if current is not None:
        return current
    if not is_web_analytics_query(query):
        return None
    if not query_has_rewritable_session_filters(query):
        return None
    # None rather than False when the flag is off: `to_dict` drops None but keeps
    # False, so returning False would change the cache key of every drilled-down
    # web analytics query even when no rewrite is applied.
    return True if first_pageview_attribution_enabled(team) else None
