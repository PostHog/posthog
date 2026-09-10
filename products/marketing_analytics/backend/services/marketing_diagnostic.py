"""End-to-end marketing analytics diagnostic.

Aggregates `data_source_health` (sync state), `attribution_health` (UTM events),
and `conversion_goals_inspector` (goal config) into a single per-integration
`overall_status`. The only service that does cross-domain reasoning: status
reflects whichever side is most broken, not an AND of "both ok".
"""

import asyncio
from collections.abc import Coroutine
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, cast

import structlog

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.marketing_analytics.backend.services.attribution_health import (
    AttributionHealthEntry,
    AttributionHealthResponse,
    get_attribution_health,
)
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    ConversionGoalsListResponse,
    list_conversion_goals,
)
from products.marketing_analytics.backend.services.data_source_health import (
    DataSourceHealthEntry,
    DataSourceHealthResponse,
    get_data_source_health,
)
from products.marketing_analytics.backend.services.native_integrations import (
    EXTERNAL_SOURCE_TYPE_TO_NATIVE,
    NATIVE_TO_KEY,
    NativeIntegration,
    display_name_for_key,
)

logger = structlog.get_logger(__name__)


@database_sync_to_async
def _load_marketing_config_snapshot(team: Team) -> tuple[dict, dict]:
    """Read the team's marketing config once and return the two slices the
    downstream services need: (sources_map, custom_source_mappings). One
    Postgres trip vs. the previous three (one per service).
    """
    config = getattr(team, "marketing_analytics_config", None)
    if config is None:
        return {}, {}
    return (config.sources_map or {}), (config.custom_source_mappings or {})


IntegrationStatus = Literal[
    "healthy",  # sync ok + events matched arriving
    "sync_broken",  # sync error/stale
    "events_broken",  # sync ok but no UTM-matched events
    "events_unmatched",  # events arrive but UTM values don't match (fb vs facebook)
    "events_only",  # no platform sync but UTM-matched events arrive (rare)
    "schema_misconfigured",  # connected and syncing but required schema columns unmapped
    "not_connected",  # no source for this integration
]

OverallStatus = Literal[
    "healthy",
    "degraded",
    "broken",
    "no_sources",
]

ActionSeverity = Literal["error", "warning", "info"]


@dataclass
class RecommendedAction:
    title: str
    detail: str
    severity: ActionSeverity
    target_tool: str | None = None  # MaxTool / MCP tool name to invoke next, if any


@dataclass
class IntegrationDiagnostic:
    integration_key: NativeIntegration
    source_type: str
    display_name: str
    overall_status: IntegrationStatus
    diagnosis: str
    data_source: DataSourceHealthEntry | None
    attribution: AttributionHealthEntry | None
    recommended_actions: list[RecommendedAction] = field(default_factory=list)


@dataclass
class MarketingDiagnosticResponse:
    integrations: list[IntegrationDiagnostic] = field(default_factory=list)
    overall_status: OverallStatus = "no_sources"
    summary: str = ""
    conversion_goals: ConversionGoalsListResponse | None = None
    recommended_actions: list[RecommendedAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def get_marketing_diagnostic(
    team: Team,
    *,
    source_type: str | None = None,
    include_conversion_goals: bool = True,
    attribution_lookback_days: int = 7,
    user: User | None = None,
) -> MarketingDiagnosticResponse:
    """Fetch all per-domain signals in parallel and combine into a unified view.

    `attribution_lookback_days` defaults to 7 (the canonical "is it healthy
    right now?" window). Widen it when the diagnostic is being asked over a
    longer period.
    """
    sources_map, custom_source_mappings = await _load_marketing_config_snapshot(team)

    coros: list[Coroutine[Any, Any, Any]] = [
        get_data_source_health(team, source_type=source_type, sources_map=sources_map),
        get_attribution_health(
            team,
            source_type=source_type,
            lookback_days=attribution_lookback_days,
            custom_source_mappings=custom_source_mappings,
        ),
    ]
    if include_conversion_goals:
        coros.append(list_conversion_goals(team, user=user))

    # `return_exceptions=True` so one failing sub-service doesn't abort the whole
    # diagnostic. Data-source and attribution health are required to diagnose, so
    # we re-raise those; conversion goals are supplementary and degrade to None.
    results = await asyncio.gather(*coros, return_exceptions=True)

    data_source_result = results[0]
    if isinstance(data_source_result, BaseException):
        logger.error("marketing_diagnostic.data_source_health_failed", team_id=team.pk, error=str(data_source_result))
        raise data_source_result
    attribution_result = results[1]
    if isinstance(attribution_result, BaseException):
        logger.error("marketing_diagnostic.attribution_health_failed", team_id=team.pk, error=str(attribution_result))
        raise attribution_result
    data_source = cast(DataSourceHealthResponse, data_source_result)
    attribution = cast(AttributionHealthResponse, attribution_result)

    goals: ConversionGoalsListResponse | None = None
    if include_conversion_goals:
        goals_result = results[2]
        if isinstance(goals_result, BaseException):
            logger.warning("marketing_diagnostic.conversion_goals_failed", team_id=team.pk, error=str(goals_result))
        else:
            goals = cast(ConversionGoalsListResponse, goals_result)

    integrations = _build_integration_diagnostics(data_source, attribution)
    overall = _compute_overall_status(integrations)
    summary = _build_summary(integrations, overall, goals)
    top_actions = _global_recommended_actions(integrations, goals)

    return MarketingDiagnosticResponse(
        integrations=integrations,
        overall_status=overall,
        summary=summary,
        conversion_goals=goals,
        recommended_actions=top_actions,
    )


def _build_integration_diagnostics(
    data_source: DataSourceHealthResponse,
    attribution: AttributionHealthResponse,
) -> list[IntegrationDiagnostic]:
    """For each integration that appears in either side, derive its overall_status,
    diagnosis text, and a small set of recommended next steps."""
    ds_by_source_type: dict[str, DataSourceHealthEntry] = {
        entry.source_type: entry for entry in data_source.integrations
    }
    attribution_by_key: dict[NativeIntegration, AttributionHealthEntry] = {
        entry.integration_key: entry for entry in attribution.integrations
    }

    diagnostics: list[IntegrationDiagnostic] = []
    seen_keys: set[NativeIntegration] = set()

    # Iterate through the canonical native list so output ordering is stable.
    for source_type_str, native in EXTERNAL_SOURCE_TYPE_TO_NATIVE.items():
        key = NATIVE_TO_KEY[native]
        seen_keys.add(key)
        ds_entry = ds_by_source_type.get(source_type_str)
        attribution_entry = attribution_by_key.get(key)
        diagnostics.append(_diagnose_one(source_type_str, key, ds_entry, attribution_entry))

    # Surface attribution-only entries (events matching an integration the team
    # never connected) — that's the `events_only` corner case.
    for key, attribution_entry in attribution_by_key.items():
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # Resolve back to the canonical source_type string for completeness.
        source_type_str = next(
            (st for st, native in EXTERNAL_SOURCE_TYPE_TO_NATIVE.items() if NATIVE_TO_KEY[native] == key),
            key,
        )
        diagnostics.append(_diagnose_one(source_type_str, key, None, attribution_entry))

    return diagnostics


def _diagnose_one(
    source_type_str: str,
    key: NativeIntegration,
    ds: DataSourceHealthEntry | None,
    attr: AttributionHealthEntry | None,
) -> IntegrationDiagnostic:
    display = display_name_for_key(key)
    actions: list[RecommendedAction] = []

    sync_ok = ds is not None and ds.connected and ds.last_sync_status == "ok"
    sync_broken = ds is not None and ds.connected and ds.last_sync_status in ("error", "stale", "never")
    tables_broken = (
        ds is not None
        and ds.connected
        and ds.last_sync_status
        in (
            "tables_failed",
            "tables_missing",
            "tables_disabled",
        )
    )
    schema_missing = ds is not None and bool(ds.schema_columns_required_missing)
    not_connected = ds is None or not ds.connected

    has_matched_events = attr is not None and attr.events_matched_last_7d > 0
    has_likely_yours = attr is not None and attr.events_unmatched_likely_yours_last_7d > 0

    if not_connected and not has_matched_events and not has_likely_yours:
        return IntegrationDiagnostic(
            integration_key=key,
            source_type=source_type_str,
            display_name=display,
            overall_status="not_connected",
            diagnosis=f"{display} is not connected and no events with matching utm_source were seen.",
            data_source=ds,
            attribution=attr,
            recommended_actions=[],
        )

    if not_connected and (has_matched_events or has_likely_yours):
        actions.append(
            RecommendedAction(
                title=f"Connect {display}",
                detail=(
                    f"Events with utm_source matching {display} are arriving "
                    f"({attr.events_matched_last_7d if attr else 0} matched, "
                    f"{attr.events_unmatched_likely_yours_last_7d if attr else 0} likely-yours), "
                    "but the platform is not connected. Connect it to enable cost/ROAS analysis."
                ),
                severity="warning",
                target_tool=None,
            )
        )
        return IntegrationDiagnostic(
            integration_key=key,
            source_type=source_type_str,
            display_name=display,
            overall_status="events_only",
            diagnosis=(
                f"{display} is not connected, but UTM-tagged events for it are arriving. "
                "Connect the platform to attribute spend to those events."
            ),
            data_source=ds,
            attribution=attr,
            recommended_actions=actions,
        )

    # `ds` is non-None past the not_connected early-returns; narrow for mypy.
    assert ds is not None

    if sync_broken or tables_broken:
        actions.append(
            RecommendedAction(
                title=f"Fix sync for {display}",
                detail=ds.fix_suggestion or "Inspect Data warehouse and retry the sync.",
                severity="error",
                target_tool=None,
            )
        )
        return IntegrationDiagnostic(
            integration_key=key,
            source_type=source_type_str,
            display_name=display,
            overall_status="sync_broken",
            diagnosis=ds.diagnosis,
            data_source=ds,
            attribution=attr,
            recommended_actions=actions,
        )

    if sync_ok and schema_missing:
        actions.append(
            RecommendedAction(
                title=f"Map required schema columns for {display}",
                detail=ds.fix_suggestion or "Open Marketing analytics settings and complete the column mapping.",
                severity="error",
                target_tool=None,
            )
        )
        return IntegrationDiagnostic(
            integration_key=key,
            source_type=source_type_str,
            display_name=display,
            overall_status="schema_misconfigured",
            diagnosis=ds.diagnosis,
            data_source=ds,
            attribution=attr,
            recommended_actions=actions,
        )

    if sync_ok and not has_matched_events and has_likely_yours:
        # `has_likely_yours` is only true when `attr is not None`; narrow for mypy.
        assert attr is not None
        actions.append(
            RecommendedAction(
                title=f"Map UTM source variants to {display}",
                detail=(
                    f"{attr.events_unmatched_likely_yours_last_7d} events look like they belong to "
                    f"{display} (e.g. 'fb', 'facebook') but don't match exactly. Use suggest_utm_mappings to "
                    "propose custom_source_mappings entries, then add them at "
                    "/settings/environment-marketing-analytics#marketing-settings."
                ),
                severity="warning",
                target_tool="marketing_suggest_utm_mappings",
            )
        )
        return IntegrationDiagnostic(
            integration_key=key,
            source_type=source_type_str,
            display_name=display,
            overall_status="events_unmatched",
            diagnosis=(
                f"{display} is syncing fine, but {attr.events_unmatched_likely_yours_last_7d} likely-{display} "
                "events arrive with UTM values that don't match. Mapping them will fix attribution."
            ),
            data_source=ds,
            attribution=attr,
            recommended_actions=actions,
        )

    if sync_ok and not has_matched_events and not has_likely_yours:
        actions.append(
            RecommendedAction(
                title=f"Verify UTM tagging for {display}",
                detail=(
                    f"{display} is syncing fine but no events with matching utm_source arrived in the last 7 "
                    "days. Check that ad URLs include the correct utm_source parameter, and that PostHog is "
                    "capturing events on the landing pages."
                ),
                severity="warning",
                target_tool="marketing_audit_utm",
            )
        )
        return IntegrationDiagnostic(
            integration_key=key,
            source_type=source_type_str,
            display_name=display,
            overall_status="events_broken",
            diagnosis=(
                f"{display} is healthy on the data side but no UTM-matched events arrived in the last 7 "
                "days. Either the platform isn't driving traffic, or UTMs aren't being captured."
            ),
            data_source=ds,
            attribution=attr,
            recommended_actions=actions,
        )

    return IntegrationDiagnostic(
        integration_key=key,
        source_type=source_type_str,
        display_name=display,
        overall_status="healthy",
        diagnosis=(
            f"{display} is healthy: syncing on schedule and "
            f"{attr.events_matched_last_7d if attr else 0} matched events in the last 7 days."
        ),
        data_source=ds,
        attribution=attr,
        recommended_actions=actions,
    )


def _compute_overall_status(integrations: list[IntegrationDiagnostic]) -> OverallStatus:
    statuses = [i.overall_status for i in integrations]
    relevant = [s for s in statuses if s != "not_connected"]
    if not relevant:
        return "no_sources"
    if all(s == "healthy" for s in relevant):
        return "healthy"
    if any(s in ("sync_broken", "schema_misconfigured") for s in relevant) and not any(
        s == "healthy" for s in relevant
    ):
        return "broken"
    return "degraded"


def _build_summary(
    integrations: list[IntegrationDiagnostic],
    overall: OverallStatus,
    goals: ConversionGoalsListResponse | None,
) -> str:
    connected_count = sum(1 for i in integrations if i.overall_status != "not_connected")
    if overall == "no_sources":
        return "No marketing integrations are connected for this project."

    healthy_count = sum(1 for i in integrations if i.overall_status == "healthy")
    if overall == "healthy":
        base = f"{healthy_count} of {connected_count} integrations are healthy."
    elif overall == "broken":
        base = f"All {connected_count} relevant integrations have problems."
    else:
        problem_count = connected_count - healthy_count
        base = f"{problem_count} of {connected_count} integrations have problems."

    if goals is not None:
        if goals.has_misconfigured:
            base += f" {sum(1 for g in goals.goals if g.is_misconfigured)} conversion goal(s) are misconfigured."
        elif goals.goals:
            base += f" {len(goals.goals)} conversion goal(s) configured."
        else:
            base += " No conversion goals configured."

    return base


def _global_recommended_actions(
    integrations: list[IntegrationDiagnostic],
    goals: ConversionGoalsListResponse | None,
) -> list[RecommendedAction]:
    """Promote per-integration actions and add cross-integration ones."""
    actions: list[RecommendedAction] = []

    if goals is not None:
        if not goals.goals:
            actions.append(
                RecommendedAction(
                    title="Configure at least one conversion goal",
                    detail=(
                        "No conversion goals are configured. Use suggest_conversion_goals to see ranked "
                        "candidates from your existing custom events."
                    ),
                    severity="warning",
                    target_tool="marketing_suggest_conversion_goals",
                )
            )
        elif goals.has_misconfigured:
            misconfigured = [g for g in goals.goals if g.is_misconfigured]
            actions.append(
                RecommendedAction(
                    title=f"Fix {len(misconfigured)} misconfigured conversion goal(s)",
                    detail=(
                        "Some conversion goals reference missing actions or DW tables: "
                        + ", ".join(g.name for g in misconfigured[:3])
                        + ("..." if len(misconfigured) > 3 else "")
                    ),
                    severity="error",
                    target_tool=None,
                )
            )

    # Lift the most severe per-integration action up to the global list, capped.
    severity_order = {"error": 0, "warning": 1, "info": 2}
    per_integration_actions: list[RecommendedAction] = []
    for integration in integrations:
        per_integration_actions.extend(integration.recommended_actions)
    per_integration_actions.sort(key=lambda a: severity_order.get(a.severity, 99))
    actions.extend(per_integration_actions[:5])

    return actions
