"""The marketing analytics setup plan: what to fix next, in machine-applicable form.

`marketing_diagnostic` explains *what is wrong*. This says *what to do about it* —
a ranked list of `Suggestion`s, each carrying an `ApplyOp` the apply endpoint can
execute, plus a readiness block saying which capabilities (cost, ROAS, CAC,
retention by channel) are unlocked and which suggestion is blocking each one.

Composition: this wraps `get_marketing_diagnostic` rather than re-deriving from the
leaf services. The diagnostic is the only service that does cross-domain reasoning
and it owns the `IntegrationStatus` ladder that the connect/reconnect/fix-sync/
map-schema suggestions map onto; re-deriving would fork that truth. The extra leaves
it doesn't expose — candidate events, the UTM catalogue, campaign rows — are fetched
alongside it in one `gather`.

Every leaf is allowed to fail independently: the diagnostic is required (without it
there's nothing to say), everything else degrades to a missing section recorded in
`degraded`, so the UI can avoid presenting a partial plan as a complete one.
"""

import asyncio
from typing import Any, cast

from django.utils import timezone

import structlog

from posthog.schema import DateRange

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.marketing_analytics.backend.services.attribution_health import (
    AttributionHealthResponse,
    get_attribution_health,
)
from products.marketing_analytics.backend.services.campaign_field_suggester import (
    FieldPreferenceSuggestion,
    suggest_campaign_field_preferences,
)
from products.marketing_analytics.backend.services.campaign_mapping_suggester import (
    CampaignMappingProposal,
    CampaignMappingSuggestions,
    suggest_campaign_name_mappings,
)
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    ConversionGoalsListResponse,
    ConversionGoalSummary,
)
from products.marketing_analytics.backend.services.event_suggestions import (
    CandidateEvent,
    EventSuggestionsResponse,
    suggest_conversion_goals,
)
from products.marketing_analytics.backend.services.mapping_suggester import (
    SourceMappingSuggestion,
    UtmMappingSuggestionsResponse,
    suggest_utm_mappings,
)
from products.marketing_analytics.backend.services.marketing_diagnostic import (
    IntegrationDiagnostic,
    MarketingDiagnosticResponse,
    get_marketing_diagnostic,
)
from products.marketing_analytics.backend.services.native_integrations import (
    KEY_TO_NATIVE,
    NativeIntegration,
    display_name_for_key,
    oauth_kind_for,
)
from products.marketing_analytics.backend.services.setup_types import (
    AddCampaignNameMapping,
    AddCustomSourceMapping,
    ApplyOp,
    Capability,
    CapabilityReadiness,
    FixPlatformUrls,
    OpenOauth,
    OpenSettings,
    OpenSourceWizard,
    ReadinessStatus,
    SetCampaignFieldPreference,
    SetupPlan,
    Severity,
    Suggestion,
    SuggestionKind,
    UpdateConversionGoal,
    sort_suggestions,
)
from products.marketing_analytics.backend.services.types import TeamMappings
from products.marketing_analytics.backend.services.utm_audit import (
    build_audit,
    get_campaigns_with_spend_async,
    get_utm_campaign_catalogue_async,
)
from products.marketing_analytics.backend.services.utm_matching import load_team_mappings

logger = structlog.get_logger(__name__)

# Matches `suggest_utm_mappings`' own default so the injected attribution fits.
ATTRIBUTION_LOOKBACK_DAYS = 90

# Every rate derived from these is a top-N subtotal, which the response flags as `truncated`.
UTM_CATALOGUE_LIMIT = 5000
CAMPAIGN_LIMIT = 500

MARKETING_SETTINGS_ANCHOR = "environment-marketing-analytics"


async def get_setup_plan(
    team: Team,
    *,
    date_from: str = "-30d",
    user: User | None = None,
) -> SetupPlan:
    """Build the ranked setup plan for a team."""
    date_range = QueryDateRange(
        date_range=DateRange(date_from=date_from, date_to=None),
        team=team,
        interval=None,
        now=timezone.now(),
    )

    results = await asyncio.gather(
        get_marketing_diagnostic(team, include_conversion_goals=True, user=user),
        get_attribution_health(team, lookback_days=ATTRIBUTION_LOOKBACK_DAYS),
        suggest_conversion_goals(team),
        get_campaigns_with_spend_async(team, date_range, user=user),
        get_utm_campaign_catalogue_async(team, date_range, user=user),
        _load_mappings(team),
        _load_goal_flags(team),
        return_exceptions=True,
    )
    (
        diagnostic_result,
        attribution_result,
        candidates_result,
        campaigns_result,
        utm_events_result,
        mappings_result,
        goal_flags_result,
    ) = results

    if isinstance(diagnostic_result, BaseException):
        # An empty plan reads as "you're all set", which is worse than an error.
        logger.exception("setup_plan.diagnostic_failed", team_id=team.pk)
        raise diagnostic_result
    # `gather` over heterogeneous coroutines collapses to a union, so narrow by position.
    diagnostic = cast(MarketingDiagnosticResponse, diagnostic_result)

    degraded: list[str] = []
    attribution = _or_degraded(attribution_result, "attribution_health", degraded, team)
    candidates = _or_degraded(candidates_result, "event_suggestions", degraded, team)
    campaigns = _or_degraded(campaigns_result, "campaigns", degraded, team) or []
    utm_events = _or_degraded(utm_events_result, "utm_catalogue", degraded, team) or {}
    mappings = _or_degraded(mappings_result, "team_mappings", degraded, team)
    goal_flags = _or_degraded(goal_flags_result, "goal_flags", degraded, team) or {}

    suggestions: list[Suggestion] = []
    suggestions.extend(_integration_suggestions(diagnostic))

    # Ahead of the mapping suggester so its proposals can be injected there.
    campaign_mappings: CampaignMappingSuggestions | None = None
    if campaigns and mappings is not None:
        # Wrapped like the gathered leaves: an unwrapped raise here would lose the diagnostic
        # and attribution results already in hand. All three together, since they read one set of rows.
        try:
            audit = build_audit(campaigns, utm_events, mappings)
            suggestions.extend(
                _field_preference_suggestions(
                    suggest_campaign_field_preferences(campaigns, utm_events, mappings, audit.results)
                )
            )
            campaign_mappings = suggest_campaign_name_mappings(campaigns, utm_events, mappings)
            suggestions.extend(_campaign_mapping_suggestions(campaign_mappings))
        except Exception as error:
            logger.warning("setup_plan.leaf_failed", leaf="campaign_suggesters", team_id=team.pk, error=str(error))
            degraded.append("campaign_suggesters")
            campaign_mappings = None

    if attribution is not None:
        utm_mappings = await _safe_utm_mappings(team, attribution, campaign_mappings, degraded)
        if utm_mappings is not None:
            suggestions.extend(_source_mapping_suggestions(utm_mappings))

    suggestions.extend(_conversion_goal_suggestions(diagnostic.conversion_goals, candidates, goal_flags))

    ranked = sort_suggestions(suggestions)
    readiness = _build_readiness(
        diagnostic=diagnostic,
        attribution=attribution,
        goal_flags=goal_flags,
        suggestions=ranked,
    )

    return SetupPlan(
        suggestions=ranked,
        readiness=readiness,
        degraded=degraded,
        truncated=len(campaigns) >= CAMPAIGN_LIMIT or len(utm_events) >= UTM_CATALOGUE_LIMIT,
        summary=_summary(ranked, readiness, degraded),
    )


def _or_degraded(result: Any, name: str, degraded: list[str], team: Team) -> Any:
    if isinstance(result, BaseException):
        logger.warning("setup_plan.leaf_failed", leaf=name, team_id=team.pk, error=str(result))
        degraded.append(name)
        return None
    return result


async def _safe_utm_mappings(
    team: Team,
    attribution: AttributionHealthResponse,
    campaign_proposals: CampaignMappingSuggestions | None,
    degraded: list[str],
) -> UtmMappingSuggestionsResponse | None:
    """Run after the gather because it consumes the gathered attribution result.

    Both inputs are injected rather than left to derive themselves: this function already holds
    them, and deriving re-reads campaigns, the UTM catalogue and team mappings from the database.
    `campaign_proposals` is None only when the plan couldn't compute them either, in which case
    letting the suggester try is the better answer.
    """
    try:
        return await suggest_utm_mappings(team, attribution=attribution, campaign_proposals=campaign_proposals)
    except Exception as error:
        logger.warning("setup_plan.leaf_failed", leaf="mapping_suggester", team_id=team.pk, error=str(error))
        degraded.append("mapping_suggester")
        return None


@database_sync_to_async
def _load_mappings(team: Team) -> TeamMappings:
    return load_team_mappings(team)


@database_sync_to_async
def _load_goal_flags(team: Team) -> dict[str, dict[str, Any]]:
    """`conversion_goal_id` -> the raw goal dict.

    `ConversionGoalSummary` doesn't carry `counts_as_revenue` / `counts_as_customer`,
    and those two booleans are exactly what gates the ROAS and CAC columns — so read
    the stored goals directly rather than widening the inspector's shape.
    """
    config = getattr(team, "marketing_analytics_config", None)
    if config is None:
        return {}
    return {
        str(goal.get("conversion_goal_id")): goal
        for goal in (config.conversion_goals or [])
        if goal.get("conversion_goal_id")
    }


# --- Suggestion builders ---------------------------------------------------


def _integration_suggestions(diagnostic: MarketingDiagnosticResponse) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    for integration in diagnostic.integrations:
        suggestion = _integration_suggestion(integration)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def _looks_like_auth_failure(last_error: str | None) -> bool:
    if not last_error:
        return False
    lowered = last_error.lower()
    return any(token in lowered for token in ("token", "unauthor", "auth", "credential", "expired", "401", "403"))


def _integration_suggestion(integration: IntegrationDiagnostic) -> Suggestion | None:
    key: NativeIntegration = integration.integration_key
    native = KEY_TO_NATIVE.get(key)
    display = integration.display_name
    status = integration.overall_status
    source_type = integration.source_type
    ds = integration.data_source
    attribution = integration.attribution
    # Both counters: `events_only` is set when either one is non-zero, so reading just the
    # likely-yours side reports "0 events" as the reason to connect a platform whose
    # utm_source matched exactly. They never overlap — a utm_source either matches an alias
    # or is only fuzzy-suggested — so the sum is every event carrying this platform's source.
    volume = (
        attribution.events_matched_last_7d + attribution.events_unmatched_likely_yours_last_7d if attribution else 0
    )

    if status == "events_only":
        # `utm_source` alone doesn't mean paid — `google` also covers gmail links and
        # `linkedin` organic posts, so this fired "connect an ad account you don't
        # have" at error severity. Suppressed only on positive evidence: most of the
        # traffic carries a medium and none of it is paid. An untagged event is absence
        # of evidence, not evidence of organic, so a tagged minority doesn't get to
        # speak for it — a team that tags its posts but not its ad links still gets asked.
        attr = integration.attribution
        if (
            attr is not None
            and attr.events_matched_paid_last_7d == 0
            and attr.events_matched_tagged_medium_last_7d * 2 > attr.events_matched_last_7d
        ):
            return None

        # Traffic arrives but no spend data, so cost, ROAS and CAC are all unavailable.
        return Suggestion(
            id=f"connect_source:{key}",
            kind=SuggestionKind.CONNECT_SOURCE,
            severity=Severity.ERROR,
            confidence=0.95,
            title=f"Connect {display}",
            evidence=(
                f"{volume:,} events in the last 7 days carry a {display} utm_source, but the platform "
                "isn't connected — none of that traffic has cost attached."
            ),
            unlocks=[Capability.COST, Capability.ROAS, Capability.CAC],
            apply=OpenSourceWizard(kind=source_type),
            integration=source_type,
            event_volume=volume,
        )

    if status == "sync_broken":
        is_auth = _looks_like_auth_failure(ds.last_error if ds else None)
        oauth_kind = oauth_kind_for(native) if native else None
        if is_auth and oauth_kind:
            return Suggestion(
                id=f"reconnect_oauth:{key}",
                kind=SuggestionKind.RECONNECT_OAUTH,
                severity=Severity.ERROR,
                confidence=0.9,
                title=f"Reconnect {display}",
                evidence=(ds.diagnosis if ds else f"{display} authentication failed.")
                + " Spend stops updating until it's reconnected.",
                unlocks=[Capability.COST, Capability.ROAS, Capability.CAC],
                apply=OpenOauth(kind=oauth_kind),
                integration=source_type,
                deep_link=ds.schemas_url if ds else None,
            )
        return Suggestion(
            id=f"fix_sync:{key}",
            kind=SuggestionKind.FIX_SYNC,
            severity=Severity.ERROR,
            confidence=0.9,
            title=f"Fix the {display} sync",
            evidence=ds.diagnosis if ds else f"{display} is not syncing.",
            unlocks=[Capability.COST, Capability.ROAS, Capability.CAC],
            apply=None,
            integration=source_type,
            deep_link=(ds.schemas_url or ds.settings_url) if ds else None,
        )

    if status == "schema_misconfigured":
        missing = ds.schema_columns_required_missing if ds else []
        return Suggestion(
            id=f"map_schema_columns:{key}",
            kind=SuggestionKind.MAP_SCHEMA_COLUMNS,
            severity=Severity.ERROR,
            confidence=0.95,
            title=f"Map required columns for {display}",
            evidence=(
                f"{display} is syncing, but {len(missing)} required column(s) aren't mapped "
                f"({', '.join(missing[:4])}). Its spend can't be read until they are."
            ),
            unlocks=[Capability.COST, Capability.ROAS, Capability.CAC],
            apply=None,
            integration=source_type,
            deep_link=(ds.settings_url if ds else None),
        )

    if status == "events_broken":
        return Suggestion(
            id=f"fix_platform_urls:{key}",
            kind=SuggestionKind.FIX_PLATFORM_URLS,
            severity=Severity.WARNING,
            confidence=0.7,
            title=f"Add UTM tags to {display} ads",
            evidence=(
                f"{display} is syncing fine but no events with a matching utm_source arrived in the "
                "last 7 days — its clicks can't be tied to anything that happens on your site."
            ),
            unlocks=[Capability.ATTRIBUTION, Capability.ROAS, Capability.CAC],
            apply=None,
            also_recommended=[
                FixPlatformUrls(
                    integration=source_type,
                    campaign_name="",
                    expected_utm_campaign="",
                    expected_utm_source=key.replace("_ads", ""),
                )
            ],
            integration=source_type,
        )

    return None


def _source_mapping_suggestions(utm_mappings: UtmMappingSuggestionsResponse) -> list[Suggestion]:
    return [_source_mapping_suggestion(s) for s in utm_mappings.source_suggestions]


def _source_mapping_suggestion(suggestion: SourceMappingSuggestion) -> Suggestion:
    native = KEY_TO_NATIVE[suggestion.suggested_target]
    display = display_name_for_key(suggestion.suggested_target)
    fix = FixPlatformUrls(
        integration=native.value,
        campaign_name="",
        expected_utm_campaign="",
        # Mapping makes the wrong value work; changing the ad URL makes it right.
        expected_utm_source=suggestion.suggested_target.replace("_ads", ""),
    )
    return Suggestion(
        id=f"add_source_mapping:{suggestion.suggested_target}:{suggestion.raw_utm_source}",
        kind=SuggestionKind.ADD_SOURCE_MAPPING,
        severity=Severity.WARNING,
        confidence=0.8,
        title=f"Map utm_source '{suggestion.raw_utm_source}' to {display}",
        evidence=(
            f"{suggestion.event_count_30d:,} events arrive tagged "
            f"utm_source={suggestion.raw_utm_source!r}, which no integration claims. "
            f"{suggestion.reason}"
        ),
        unlocks=[Capability.ATTRIBUTION, Capability.ROAS, Capability.CAC],
        apply=AddCustomSourceMapping(integration=native.value, raw_utm_source=suggestion.raw_utm_source),
        safe_to_batch=True,
        integration=native.value,
        event_volume=suggestion.event_count_30d,
        also_recommended=[fix],
    )


def _field_preference_suggestions(field_suggestions: list[FieldPreferenceSuggestion]) -> list[Suggestion]:
    return [
        Suggestion(
            id=f"switch_campaign_match_field:{s.integration}",
            kind=SuggestionKind.SWITCH_CAMPAIGN_MATCH_FIELD,
            severity=Severity.ERROR if not s.triggered_by_collision else Severity.WARNING,
            confidence=s.confidence,
            title=f"Match {s.integration_display_name} campaigns by {s.suggested_match_field.replace('_', ' ')}",
            evidence=s.reason,
            unlocks=[Capability.ROAS, Capability.CAC],
            apply=SetCampaignFieldPreference(
                integration=s.integration,
                match_field=s.suggested_match_field,
            ),
            safe_to_batch=s.safe_to_batch,
            integration=s.integration,
            spend_at_risk=s.spend_at_risk,
        )
        for s in field_suggestions
    ]


def _campaign_mapping_suggestions(result: CampaignMappingSuggestions) -> list[Suggestion]:
    suggestions = [_campaign_mapping_suggestion(p) for p in result.proposals]

    for unresolved in result.unresolved[:5]:
        suggestions.append(
            Suggestion(
                id=f"fix_platform_urls:orphan:{unresolved.raw_utm_campaign}",
                kind=SuggestionKind.FIX_PLATFORM_URLS,
                severity=Severity.WARNING,
                confidence=0.6,
                title=f"'{unresolved.raw_utm_campaign}' matches no campaign",
                evidence=(
                    f"{unresolved.event_count:,} events arrive tagged "
                    f"utm_campaign={unresolved.raw_utm_campaign!r} (utm_source="
                    f"{unresolved.observed_utm_source!r}). {unresolved.reason}"
                ),
                unlocks=[Capability.ATTRIBUTION],
                apply=None,
                event_volume=unresolved.event_count,
            )
        )
    return suggestions


def _campaign_mapping_suggestion(proposal: CampaignMappingProposal) -> Suggestion:
    fix = FixPlatformUrls(
        integration=proposal.integration,
        campaign_name=proposal.clean_name,
        expected_utm_campaign=proposal.expected_utm_campaign,
        expected_utm_source=proposal.expected_utm_source,
    )
    return Suggestion(
        id=f"add_campaign_name_mapping:{proposal.integration}:{proposal.raw_utm_campaign}",
        kind=SuggestionKind.ADD_CAMPAIGN_NAME_MAPPING,
        severity=Severity.WARNING,
        confidence=proposal.confidence,
        title=f"Link '{proposal.raw_utm_campaign}' to '{proposal.clean_name}'",
        evidence=proposal.reason,
        unlocks=[Capability.ROAS, Capability.CAC],
        apply=AddCampaignNameMapping(
            integration=proposal.integration,
            clean_name=proposal.clean_name,
            raw_values=[proposal.raw_utm_campaign],
        ),
        safe_to_batch=proposal.safe_to_batch,
        integration=proposal.integration,
        spend_at_risk=proposal.campaign_spend,
        event_volume=proposal.event_count,
        also_recommended=[fix],
    )


def _conversion_goal_suggestions(
    goals: ConversionGoalsListResponse | None,
    candidates: EventSuggestionsResponse | None,
    goal_flags: dict[str, dict[str, Any]],
) -> list[Suggestion]:
    # `_missing_flag_suggestion` returns None when no goal is worth it; the comprehension drops those.
    suggestions: list[Suggestion | None] = []

    if goals is None or not goals.goals:
        suggestions.extend(_create_goal_suggestions(candidates))
        return [s for s in suggestions if s is not None]

    for goal in goals.goals:
        if goal.is_misconfigured:
            suggestions.append(_fix_goal_suggestion(goal))

    if not any(goal_flags.get(g.conversion_goal_id, {}).get("counts_as_revenue") for g in goals.goals):
        suggestions.append(_missing_flag_suggestion(goals.goals, goal_flags, revenue=True))
    if not any(goal_flags.get(g.conversion_goal_id, {}).get("counts_as_customer") for g in goals.goals):
        suggestions.append(_missing_flag_suggestion(goals.goals, goal_flags, revenue=False))

    return [s for s in suggestions if s is not None]


def _create_goal_suggestions(candidates: EventSuggestionsResponse | None) -> list[Suggestion]:
    if candidates is None or not candidates.candidates:
        return [
            Suggestion(
                id="create_conversion_goal:none",
                kind=SuggestionKind.CREATE_CONVERSION_GOAL,
                severity=Severity.WARNING,
                confidence=0.9,
                title="Add a conversion goal",
                evidence=(
                    "No conversion goals are configured, so the dashboard can only show spend — "
                    "no conversions, ROAS or cost per customer."
                ),
                unlocks=[Capability.ROAS, Capability.CAC],
                apply=OpenSettings(anchor=MARKETING_SETTINGS_ANCHOR),
            )
        ]

    # Name the best candidate and link out. Picking the revenue property is a semantic call the
    # AI layer makes, not a volume ranking.
    top: CandidateEvent = candidates.candidates[0]
    return [
        Suggestion(
            id="create_conversion_goal:top_candidate",
            kind=SuggestionKind.CREATE_CONVERSION_GOAL,
            severity=Severity.WARNING,
            confidence=0.75,
            title=f"Make '{top.event_name}' a conversion goal",
            evidence=(
                f"No conversion goals are configured. '{top.event_name}' fired {top.last_30d_count:,} times "
                f"in the last 30 days across {top.distinct_users_30d:,} users, and "
                f"{top.pct_with_utm_source:.0%} of those carry a utm_source — the best-attributable "
                "candidate in your data."
            ),
            unlocks=[Capability.ROAS, Capability.CAC],
            apply=OpenSettings(anchor=MARKETING_SETTINGS_ANCHOR),
            event_volume=top.last_30d_count,
        )
    ]


def _fix_goal_suggestion(goal: ConversionGoalSummary) -> Suggestion:
    return Suggestion(
        id=f"fix_conversion_goal:{goal.conversion_goal_id}",
        kind=SuggestionKind.FIX_CONVERSION_GOAL,
        severity=Severity.ERROR,
        confidence=0.95,
        title=f"Fix the '{goal.name}' conversion goal",
        evidence=goal.misconfig_reason or "This goal references something that no longer exists.",
        unlocks=[Capability.ROAS, Capability.CAC],
        apply=OpenSettings(anchor=MARKETING_SETTINGS_ANCHOR),
    )


def _missing_flag_suggestion(
    goals: list[ConversionGoalSummary],
    goal_flags: dict[str, dict[str, Any]],
    *,
    revenue: bool,
) -> Suggestion | None:
    """Nudge to flag one goal as revenue- or customer-bearing.

    Without `counts_as_revenue` there is no ROAS column, and without
    `counts_as_customer` there is no cost-per-customer — the goals exist but the
    two headline metrics stay empty, with nothing on the dashboard explaining why.
    Which goal deserves the flag is a business call, so this links out rather than
    picking one.
    """
    candidate = max(goals, key=lambda g: g.last_30d_count, default=None)
    if candidate is None:
        return None

    kind = SuggestionKind.MARK_GOAL_AS_REVENUE if revenue else SuggestionKind.MARK_GOAL_AS_CUSTOMER
    metric = "ROAS" if revenue else "cost per customer"
    flag = "counts_as_revenue" if revenue else "counts_as_customer"
    return Suggestion(
        id=f"{kind.value}:any",
        kind=kind,
        severity=Severity.WARNING,
        confidence=0.7,
        title=f"Mark a conversion goal as {'revenue-bearing' if revenue else 'customer-defining'}",
        evidence=(
            f"{len(goals)} conversion goal(s) are configured but none has `{flag}` set, so the "
            f"{metric} column stays empty. '{candidate.name}' is the highest-volume candidate "
            f"({candidate.last_30d_count:,} in 30 days)."
        ),
        unlocks=[Capability.ROAS if revenue else Capability.CAC],
        # Which goal counts as revenue is a business decision, not a config fix.
        apply=UpdateConversionGoal(conversion_goal_id=candidate.conversion_goal_id, patch={flag: True}),
        safe_to_batch=False,
        event_volume=candidate.last_30d_count,
    )


# --- Readiness -------------------------------------------------------------


def _blockers(suggestions: list[Suggestion], capability: Capability) -> list[str]:
    return [s.id for s in suggestions if capability in s.unlocks]


def _build_readiness(
    *,
    diagnostic: MarketingDiagnosticResponse,
    attribution: AttributionHealthResponse | None,
    goal_flags: dict[str, dict[str, Any]],
    suggestions: list[Suggestion],
) -> list[CapabilityReadiness]:
    healthy = [i for i in diagnostic.integrations if i.overall_status in ("healthy", "events_unmatched")]
    relevant = [i for i in diagnostic.integrations if i.overall_status != "not_connected"]

    if not relevant:
        cost_status, cost_why = ReadinessStatus.BLOCKED, "No ad platform is connected, so there is no spend data."
    elif len(healthy) == len(relevant):
        cost_status, cost_why = ReadinessStatus.UNLOCKED, f"{len(healthy)} integration(s) are syncing spend."
    elif healthy:
        cost_status = ReadinessStatus.PARTIAL
        cost_why = f"Spend is available for {len(healthy)} of {len(relevant)} connected integrations."
    else:
        cost_status, cost_why = ReadinessStatus.BLOCKED, "Every connected integration has a problem reading spend."

    attribution_status, attribution_why = _attribution_readiness(attribution)
    has_revenue_goal = any(g.get("counts_as_revenue") for g in goal_flags.values())
    has_customer_goal = any(g.get("counts_as_customer") for g in goal_flags.values())

    return [
        CapabilityReadiness(
            capability=Capability.COST,
            status=cost_status,
            explanation=cost_why,
            blocked_by=_blockers(suggestions, Capability.COST),
        ),
        CapabilityReadiness(
            capability=Capability.ATTRIBUTION,
            status=attribution_status,
            explanation=attribution_why,
            blocked_by=_blockers(suggestions, Capability.ATTRIBUTION),
        ),
        _metric_readiness(
            Capability.ROAS,
            cost_status,
            has_goal=has_revenue_goal,
            goal_hint="no conversion goal is marked `counts_as_revenue`",
            suggestions=suggestions,
        ),
        _metric_readiness(
            Capability.CAC,
            cost_status,
            has_goal=has_customer_goal,
            goal_hint="no conversion goal is marked `counts_as_customer`",
            suggestions=suggestions,
        ),
    ]


def _attribution_readiness(attribution: AttributionHealthResponse | None) -> tuple[ReadinessStatus, str]:
    if attribution is None:
        return ReadinessStatus.BLOCKED, "Attribution health could not be read."
    total = attribution.total_events_with_utm
    if total == 0:
        return (
            ReadinessStatus.BLOCKED,
            "No events with a utm_source arrived in the window — nothing can be attributed to a channel.",
        )
    matched_pct = attribution.total_events_matched_to_any_integration / total
    approx = " (top-N subtotal)" if attribution.utm_source_catalogue_truncated else ""
    if matched_pct >= 0.8:
        return ReadinessStatus.UNLOCKED, f"{matched_pct:.0%} of UTM-tagged events match a connected platform{approx}."
    if matched_pct > 0:
        return (
            ReadinessStatus.PARTIAL,
            f"Only {matched_pct:.0%} of UTM-tagged events match a connected platform{approx}; the rest "
            "can't be attributed to spend.",
        )
    return ReadinessStatus.BLOCKED, "UTM-tagged events arrive but none match a connected platform."


def _metric_readiness(
    capability: Capability,
    cost_status: ReadinessStatus,
    *,
    has_goal: bool,
    goal_hint: str,
    suggestions: list[Suggestion],
) -> CapabilityReadiness:
    blocked_by = _blockers(suggestions, capability)
    if cost_status == ReadinessStatus.BLOCKED and not has_goal:
        explanation = f"Needs spend data and a conversion goal: spend is unavailable and {goal_hint}."
        status = ReadinessStatus.BLOCKED
    elif not has_goal:
        explanation = f"Spend is available, but {goal_hint}."
        status = ReadinessStatus.BLOCKED
    elif cost_status == ReadinessStatus.BLOCKED:
        explanation = "A goal is flagged, but there is no spend data to divide by."
        status = ReadinessStatus.BLOCKED
    elif cost_status == ReadinessStatus.PARTIAL:
        explanation = "Available, but only for the integrations whose spend is readable."
        status = ReadinessStatus.PARTIAL
    else:
        explanation = "Spend and a flagged conversion goal are both in place."
        status = ReadinessStatus.UNLOCKED
    return CapabilityReadiness(capability=capability, status=status, explanation=explanation, blocked_by=blocked_by)


def _summary(suggestions: list[Suggestion], readiness: list[CapabilityReadiness], degraded: list[str]) -> str:
    if not suggestions:
        return "Nothing to fix — every check passed."
    errors = sum(1 for s in suggestions if s.severity == Severity.ERROR)
    unlocked = sum(1 for r in readiness if r.status == ReadinessStatus.UNLOCKED)
    partial = sum(1 for r in readiness if r.status == ReadinessStatus.PARTIAL)
    # Partial counted separately: "0 of 4 unlocked" reads as nothing working, and a team whose
    # four capabilities are all partial is in a very different place from one where they're blocked.
    capabilities = f"{unlocked} of {len(readiness)} capabilities unlocked"
    if partial:
        capabilities += f", {partial} partial"
    parts = [
        f"{len(suggestions)} suggestion(s), {errors} blocking.",
        f"{capabilities}.",
    ]
    if degraded:
        parts.append(f"Incomplete: {', '.join(degraded)} could not be read.")
    return " ".join(parts)


__all__ = ["ApplyOp", "get_setup_plan"]
