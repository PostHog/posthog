"""MaxTool wrappers around Marketing analytics services.

The LangChain surface (args schema, descriptions, context, access checks) lives
here; the business logic lives in `services/`.
"""

from dataclasses import asdict
from datetime import datetime
from textwrap import dedent
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

import structlog
from pydantic import BaseModel, Field

from posthog.schema import DateRange

from posthog.models.team.team import Team
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject
from posthog.security.llm_prompt_sanitization import GENERIC_VALUE_MAX_LEN, sanitize_user_text
from posthog.sync import database_sync_to_async
from posthog.utils import relative_date_parse

from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    explain_conversion_goal,
    list_conversion_goals,
)
from products.marketing_analytics.backend.services.data_source_health import get_data_source_health
from products.marketing_analytics.backend.services.event_suggestions import suggest_conversion_goals
from products.marketing_analytics.backend.services.mapping_suggester import suggest_utm_mappings
from products.marketing_analytics.backend.services.marketing_diagnostic import get_marketing_diagnostic
from products.marketing_analytics.backend.services.utm_audit import run_utm_audit

from ee.hogai.tool import MaxTool

logger = structlog.get_logger(__name__)

# Cap attribution scans server-side: an unbounded utm_source scan over multi-year
# windows can pin a ClickHouse node on a high-volume team, and this surface isn't interactive.
MAX_LOOKBACK_DAYS = 365

# Shared context for tools mounted on /marketing — keeps the root node from
# conflating Marketing with Web analytics or misstating the attribution model.
MARKETING_CONTEXT_PROMPT = dedent("""
    User is on /marketing — the Marketing analytics product, NOT Web analytics.

    Distinctions to keep in mind:
    - Marketing analytics 'Reported conversions' = numbers PULLED from connected ad platforms via their APIs (Google Ads metrics_conversions, Meta CAPI, etc.). PostHog does not compute these.
    - Marketing analytics 'Conversion goals' = PostHog events/actions configured by the team to be matched with UTM-tagged sessions for attribution.
    - Web analytics 'Goals' are a SEPARATE concept from Marketing analytics conversion goals; do not conflate them.
    - Marketing analytics is a built-in feature page at /marketing, not a configurable dashboard. Its tabular view cannot be added as a component to other dashboards.
    - Marketing analytics supports first-touch, last-touch, and multi-touch attribution (linear, time-decay, position-based). The team's active model is reported as `attribution_mode` by the conversion-goal tools — read it rather than assuming. Multi-touch distributes conversion credit across the UTM touchpoints seen within the team's attribution window before each conversion. ML-based "data-driven" attribution is not available.

    Current filters: {current_filters}
    Current date range: {current_date_range}
    Configured custom_source_mappings count: {custom_source_mappings_count}
    Configured campaign_name_mappings count: {campaign_name_mappings_count}
    Existing conversion goal count: {existing_goal_count}
""").strip()


def _marketing_resource() -> list[tuple[APIScopeObject, AccessControlLevel]]:
    return [("marketing_analytics", "viewer")]


def _lookback_days_from_date_range(team: Team, date_range: dict | None) -> int | None:
    """Convert the frontend `current_date_range` to a lookback in days, parsed in the
    team's timezone (relative or ISO). Returns None when unparseable."""
    if not date_range or not isinstance(date_range, dict):
        return None
    raw_from = date_range.get("date_from")
    if not raw_from:
        return None
    raw_to = date_range.get("date_to")

    tz = ZoneInfo(team.timezone)
    try:
        start = relative_date_parse(str(raw_from), tz)
        end = relative_date_parse(str(raw_to), tz) if raw_to else timezone.now().astimezone(tz)
    except Exception:
        logger.warning("marketing_lookback_date_parse_failed", team_id=team.pk, date_range=date_range)
        return None

    delta = (end - start).days
    return delta if delta > 0 else None


def _resolve_lookback_days(team: Team, self_context: dict, requested: int | None, fallback: int) -> int:
    """Resolve `lookback_days`: explicit > inferred-from-context > fallback, all
    clamped to MAX_LOOKBACK_DAYS."""
    if requested is not None and requested > 0:
        return min(requested, MAX_LOOKBACK_DAYS)
    inferred = _lookback_days_from_date_range(team, self_context.get("current_date_range"))
    if inferred is not None:
        return min(inferred, MAX_LOOKBACK_DAYS)
    return min(fallback, MAX_LOOKBACK_DAYS)


# ---------- Tool 1: marketing_diagnose_setup ----------


class MarketingDiagnoseSetupArgs(BaseModel):
    include_conversion_goals: bool = Field(
        default=True,
        description="Whether to also load conversion goals as part of the diagnostic. Set to False for a faster sync+attribution-only check.",
    )
    source_type: str | None = Field(
        default=None,
        description="Optional. Filter the diagnostic to one integration (e.g. 'GoogleAds', 'MetaAds').",
    )
    attribution_lookback_days: int | None = Field(
        default=None,
        ge=1,
        le=1095,
        description=(
            "Days of event history used for the attribution side. By default the tool reads the "
            "user's currently visible date range from context (typically what they're looking at "
            "in the dashboard) and uses that. Pass an explicit value (e.g. 7, 90, 365) only when "
            "the user asks for a different window than what they're currently viewing."
        ),
    )


class MarketingDiagnoseSetupTool(MaxTool):
    name: str = "marketing_diagnose_setup"
    description: str = dedent("""
        READ-ONLY end-to-end diagnostic of Marketing analytics for the current project.

        Returns:
        - Per-integration overall_status (healthy / sync_broken / events_broken / events_unmatched / events_only / schema_misconfigured / not_connected)
        - Sync state (last_sync_at, errors, row counts, schema mapping coverage)
        - Attribution state (UTM-tagged events arriving, matched vs likely-yours-but-unmatched)
        - Conversion goals with last-30d performance and misconfig flags
        - Recommended next actions, each pointing to the right follow-up tool

        USE THIS TOOL FIRST whenever the user asks why marketing analytics looks wrong, missing, or broken. Do NOT speculate about causes before calling this tool.
    """).strip()
    context_prompt_template: str = MARKETING_CONTEXT_PROMPT
    args_schema: type[BaseModel] = MarketingDiagnoseSetupArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return _marketing_resource()

    async def _arun_impl(
        self,
        include_conversion_goals: bool = True,
        source_type: str | None = None,
        attribution_lookback_days: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        resolved_lookback = _resolve_lookback_days(self._team, self.context, attribution_lookback_days, fallback=7)
        response = await get_marketing_diagnostic(
            self._team,
            source_type=source_type,
            include_conversion_goals=include_conversion_goals,
            attribution_lookback_days=resolved_lookback,
        )
        return _format_diagnostic_for_llm(response), response.to_dict()


# ---------- Tool 2: marketing_explain_conversion_goal ----------


class MarketingExplainConversionGoalArgs(BaseModel):
    goal_id: str = Field(
        description="The id of the conversion goal to explain. Must match an id from `marketing_list_conversion_goals`.",
    )
    date_from: str | None = Field(
        default=None,
        description="ISO 8601 start of the period to explain. Defaults to 30 days ago.",
    )
    date_to: str | None = Field(
        default=None,
        description="ISO 8601 end of the period to explain. Defaults to now.",
    )


class MarketingExplainConversionGoalTool(MaxTool):
    name: str = "marketing_explain_conversion_goal"
    description: str = dedent("""
        Break down the events that COUNT toward a conversion goal by their own utm_source, utm_campaign, and matched integration. Returns recent sample events for inspection.

        This is a flat per-event breakdown of the conversion events themselves — NOT an analysis of the user's prior journey, and NOT the dashboard's attribution calculation (first-touch / last-touch / multi-touch weighting is applied by the dashboard, not here).

        Use this when the user asks "what utm_sources are behind my N conversions?" or "where do these conversions come from?".

        Only EventsNode and ActionsNode goals are explained at the event level. DataWarehouseNode goals are computed against external tables and short-circuit with a note.
    """).strip()
    context_prompt_template: str = MARKETING_CONTEXT_PROMPT
    args_schema: type[BaseModel] = MarketingExplainConversionGoalArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return _marketing_resource()

    async def _arun_impl(
        self, goal_id: str, date_from: str | None = None, date_to: str | None = None
    ) -> tuple[str, dict[str, Any]]:
        period = None
        if date_from or date_to:
            period = DateRange(date_from=date_from, date_to=date_to)
        try:
            response = await explain_conversion_goal(self._team, goal_id, period=period)
        except ValueError as exc:
            return f"Could not explain goal: {exc}", {"error": "goal_not_found", "goal_id": goal_id}
        return _format_explain_goal_for_llm(response), response.to_dict()


# ---------- Tool 3: marketing_list_conversion_goals ----------


class MarketingListConversionGoalsArgs(BaseModel):
    pass


class MarketingListConversionGoalsTool(MaxTool):
    name: str = "marketing_list_conversion_goals"
    description: str = dedent("""
        Read the configured conversion goals for the current project. Each goal is returned with its kind (EventsNode / ActionsNode / DataWarehouseNode), target label, last-30d count, integrated vs non-integrated split, and a misconfiguration flag.

        Use this BEFORE answering any question about which events are conversion goals or how many conversions there are.
    """).strip()
    context_prompt_template: str = MARKETING_CONTEXT_PROMPT
    args_schema: type[BaseModel] = MarketingListConversionGoalsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return _marketing_resource()

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        response = await list_conversion_goals(self._team)
        return _format_conversion_goals_for_llm(response), response.to_dict()


# ---------- Tool 4: marketing_list_data_sources ----------


class MarketingListDataSourcesArgs(BaseModel):
    source_type: str | None = Field(
        default=None,
        description="Optional. Restrict to one integration (e.g. 'GoogleAds').",
    )


class MarketingListDataSourcesTool(MaxTool):
    name: str = "marketing_list_data_sources"
    description: str = dedent("""
        List the platform-side health of every native marketing integration: connected/not, last sync time and status, last error, rows synced, and schema-mapping coverage.

        This is the platform → DW side only. For PostHog-events-side health (UTM matching), call `marketing_diagnose_setup`.
    """).strip()
    context_prompt_template: str = MARKETING_CONTEXT_PROMPT
    args_schema: type[BaseModel] = MarketingListDataSourcesArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return _marketing_resource()

    async def _arun_impl(self, source_type: str | None = None) -> tuple[str, dict[str, Any]]:
        response = await get_data_source_health(self._team, source_type=source_type)
        return _format_data_sources_for_llm(response), response.to_dict()


# ---------- Tool 5: marketing_audit_utm ----------


class MarketingAuditUtmArgs(BaseModel):
    pass


class MarketingAuditUtmTool(MaxTool):
    name: str = "marketing_audit_utm"
    description: str = dedent("""
        Audit the UTM tagging quality of recent events: campaigns with issues, mismatched utm_source vs configured integrations, unmatched custom sources, and total spend at risk.

        Use when the user asks why their events appear in 'non-integrated', or why UTMs are not matching the ad platform data.
    """).strip()
    context_prompt_template: str = MARKETING_CONTEXT_PROMPT
    args_schema: type[BaseModel] = MarketingAuditUtmArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return _marketing_resource()

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        # `run_utm_audit` is sync (legacy contract); wrap with the standard async helper.
        response = await database_sync_to_async(run_utm_audit)(self._team)
        return _format_audit_utm_for_llm(response), asdict(response)


# ---------- Tool 6: marketing_suggest_conversion_goals ----------


class MarketingSuggestConversionGoalsArgs(BaseModel):
    top_n: int = Field(default=10, ge=1, le=50)
    min_count: int = Field(
        default=50, ge=0, description="Minimum 30d event count for an event to be considered a candidate."
    )


class MarketingSuggestConversionGoalsTool(MaxTool):
    name: str = "marketing_suggest_conversion_goals"
    description: str = dedent("""
        Suggest custom events that are good candidates for becoming conversion goals. Ranks by volume, UTM tag coverage, and uniqueness of users. Excludes autocapture/system events and events that are already configured as goals.
    """).strip()
    context_prompt_template: str = MARKETING_CONTEXT_PROMPT
    args_schema: type[BaseModel] = MarketingSuggestConversionGoalsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return _marketing_resource()

    async def _arun_impl(self, top_n: int = 10, min_count: int = 50) -> tuple[str, dict[str, Any]]:
        response = await suggest_conversion_goals(self._team, top_n=top_n, min_count=min_count)
        return _format_event_suggestions_for_llm(response), response.to_dict()


# ---------- Tool 7: marketing_suggest_utm_mappings ----------


class MarketingSuggestUtmMappingsArgs(BaseModel):
    min_event_count: int = Field(
        default=10,
        ge=0,
        description="Only suggest mappings for raw values with at least this many events in the lookback window.",
    )
    lookback_days: int | None = Field(
        default=None,
        ge=1,
        le=1095,
        description=(
            "Days of event history to inspect. By default the tool reads the user's currently "
            "visible date range from context (typically what they're looking at in the dashboard). "
            "Pass an explicit value (e.g. 90, 365) only when the user asks for a different window "
            "than what they're currently viewing. Falls back to 90 if context has no date range."
        ),
    )


class MarketingSuggestUtmMappingsTool(MaxTool):
    name: str = "marketing_suggest_utm_mappings"
    description: str = dedent("""
        USE THIS TOOL — DO NOT FALL BACK TO SQL — whenever the user asks about utm_source mappings, custom_source_mappings, unmatched / non-integrated UTM values, or the question "what utm_sources do I have and which ad platform do they belong to?".

        Returns:
        - `full_utm_source_catalogue`: every utm_source value seen on events in the window (matched + unmatched), with event count and which integration it resolves to (if any). Use this to answer "which UTMs are arriving" without running SQL.
        - `source_suggestions`: mapping recommendations where a value's token matches a known alias (e.g. raw `facebook_paid` → MetaAds). For ambiguous values (typos like `fcebook`, novel sources) use `raw_unmatched_samples` and judge them yourself.
        - `raw_unmatched_samples`: every unmatched value (including likely-not-an-ad values like `organic`, `newsletter`, `partner`).
        - `current_mappings`: every alias already in effect (canonical + team_custom) so you don't suggest duplicates.

        Defaults to last 90 days. Pass `lookback_days=365` (or more) when the user asks about a longer period or when 90 days returns no UTMs.

        Read-only — applying mappings is a separate write tool (Phase 2).
    """).strip()
    context_prompt_template: str = MARKETING_CONTEXT_PROMPT
    args_schema: type[BaseModel] = MarketingSuggestUtmMappingsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return _marketing_resource()

    async def _arun_impl(
        self,
        min_event_count: int = 10,
        lookback_days: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        resolved_lookback = _resolve_lookback_days(self._team, self.context, lookback_days, fallback=90)
        response = await suggest_utm_mappings(
            self._team,
            min_event_count=min_event_count,
            lookback_days=resolved_lookback,
        )
        return _format_utm_mapping_suggestions_for_llm(response), response.to_dict()


# --------------------------------------------------------------------------
# LLM-facing content formatters
# --------------------------------------------------------------------------
# These turn a service response into the string the LLM uses to compose its reply,
# so it must carry every datum the LLM needs. The `artifact` (dict) is for the frontend.


def _sanitize_for_prompt(value: Any, max_len: int = GENERIC_VALUE_MAX_LEN) -> str:
    """Sanitize a user-controlled event property for an LLM prompt: `<none>` for empty,
    `…` on truncation. Coerces non-string values (event properties can be numbers)."""
    text = str(value) if value is not None else None
    return sanitize_user_text(text, max_len, none_placeholder="<none>", truncate_marker="…")


def _format_timestamp_for_llm(dt: datetime | None) -> str:
    """Render a timestamp with a pre-computed relative age — LLMs do date arithmetic
    unreliably, so we compute "how long ago" here rather than letting the model."""
    if dt is None:
        return "never"
    delta_days = (timezone.now() - dt).days
    if delta_days < 0:
        rel = "in the future — clock skew?"
    elif delta_days == 0:
        rel = "today"
    elif delta_days == 1:
        rel = "1 day ago"
    else:
        rel = f"{delta_days} days ago"
    return f"{dt:%Y-%m-%d %H:%M} UTC ({rel})"


def _format_diagnostic_for_llm(response) -> str:
    lines: list[str] = [
        "# Marketing analytics diagnostic",
        f"Overall status: **{response.overall_status}** — {response.summary}",
        "",
        "REPORTING INSTRUCTIONS for the assistant:",
        "- DO NOT agglomerate integrations into a single sentence (avoid phrasings like 'X integrations have schema issues').",
        "- For every connected integration with an issue, name it explicitly and list its specific missing tables / columns / errors.",
        "- Always include the `settings_url` and `fix_suggestion` so the user can click straight to the fix.",
        "- `matched_pct` is matched events ÷ ALL team events carrying any utm_source — NOT a share of ad-platform clicks or impressions. Never describe it as 'X% of clicks'.",
        "- Report sync timestamps exactly as given; the relative age is already computed — do not recompute it.",
        "",
    ]

    integrations = response.integrations or []
    if integrations:
        lines.append("## Integrations (report each one individually)")
        for entry in integrations:
            lines.append(f"### {entry.display_name} (`{entry.source_type}`) — status: `{entry.overall_status}`")
            lines.append(f"- diagnosis: {_sanitize_for_prompt(entry.diagnosis, max_len=500)}")
            ds = entry.data_source
            if ds is not None:
                lines.append(f"- settings_url: {ds.settings_url}")
                if ds.schemas_url:
                    lines.append(
                        f"- schemas_url: {ds.schemas_url} (per-source Schemas tab — for table enable/disable, retry failed syncs, reconnect)"
                    )
                if ds.fix_suggestion:
                    lines.append(f"- fix_suggestion: {_sanitize_for_prompt(ds.fix_suggestion, max_len=500)}")
            if ds is not None and ds.connected:
                last_sync = _format_timestamp_for_llm(ds.last_sync_at)
                lines.append(
                    f"- sync: `{ds.last_sync_status}`, last_sync_at={last_sync}, "
                    f"sync_activity_24h={ds.rows_last_24h} rows processed, "
                    f"sync_activity_7d={ds.rows_last_7d} rows processed "
                    f"(this is total sync throughput across all jobs in the window — "
                    f"not the row count of the source table)"
                )
                if ds.last_error:
                    # Third-party connector error body — highest-risk injection surface here.
                    lines.append(f"- last_error: {_sanitize_for_prompt(ds.last_error)}")
                if ds.schema_columns_required_missing:
                    lines.append(f"- schema_columns_required_missing: {', '.join(ds.schema_columns_required_missing)}")
                if ds.required_tables:
                    table_lines = []
                    for t in ds.required_tables:
                        if not t.present:
                            table_lines.append(f"`{t.table_name}` (missing)")
                        elif not t.should_sync:
                            table_lines.append(f"`{t.table_name}` (disabled, status={t.status})")
                        elif t.status == "Failed":
                            table_lines.append(f"`{t.table_name}` (FAILED)")
                        else:
                            table_lines.append(f"`{t.table_name}` ({t.status or 'unknown'})")
                    lines.append(f"- required_tables: {', '.join(table_lines)}")
            attr = entry.attribution
            if attr is not None:
                lines.append(
                    f"- events: matched {attr.events_matched_last_7d} of "
                    f"{attr.events_with_utm_last_7d} team events-with-utm_source ({attr.matched_pct}%), "
                    f"likely-yours-but-unmatched={attr.events_unmatched_likely_yours_last_7d}"
                )
                if attr.sample_unmatched_utm_sources:
                    samples = ", ".join(
                        f"{_sanitize_for_prompt(s.raw_value)}({s.event_count})"
                        for s in attr.sample_unmatched_utm_sources[:5]
                    )
                    lines.append(f"- likely-yours unmatched samples: {samples}")
            for action in entry.recommended_actions or []:
                tool_hint = f" → call `{action.target_tool}`" if action.target_tool else ""
                lines.append(f"- **action ({action.severity})**: {action.title}{tool_hint}")
                if action.detail:
                    lines.append(f"    {action.detail}")
            lines.append("")

    goals_resp = response.conversion_goals
    if goals_resp is not None:
        lines.append("## Conversion goals")
        lines.append(
            f"Attribution: `{goals_resp.attribution_mode}`, window: {goals_resp.attribution_window_days}d. "
            f"{len(goals_resp.goals)} configured."
        )
        lines.append("")
        lines.append(_NON_INTEGRATED_SPLIT_INSTRUCTIONS)
        lines.append("")
        for goal in goals_resp.goals or []:
            lines.append(_format_goal_line(goal))
        lines.append("")

    if response.recommended_actions:
        lines.append("## Top recommended actions")
        for action in response.recommended_actions:
            tool_hint = f" → call `{action.target_tool}`" if action.target_tool else ""
            lines.append(f"- **({action.severity})** {action.title}{tool_hint}")
            if action.detail:
                lines.append(f"  {action.detail}")

    return "\n".join(lines)


def _format_conversion_goals_for_llm(response) -> str:
    if not response.goals:
        return "No conversion goals are configured for this project."
    lines: list[str] = [
        f"Attribution: `{response.attribution_mode}`, window: {response.attribution_window_days}d. "
        f"{len(response.goals)} configured. "
        f"{'Some goals are misconfigured.' if response.has_misconfigured else 'All goals look valid.'}",
        "",
        _NON_INTEGRATED_SPLIT_INSTRUCTIONS,
        "",
    ]
    for goal in response.goals:
        lines.append(_format_goal_line(goal, include_id=True))
    return "\n".join(lines)


_NON_INTEGRATED_SPLIT_INSTRUCTIONS = dedent("""
    REPORTING INSTRUCTIONS for `non_integrated_count` (CRITICAL — has two root causes with OPPOSITE fixes):

    `non_integrated_count` = `events_without_utm_source` + `events_with_unmatched_utm_source`. These have DIFFERENT fixes:

    - `events_without_utm_source`: the conversion event has NO `utm_source` property at all (the user landed without UTM tags, or the SDK is set up without UTM persistence).
        Fix: tag the ad URLs with utm_source/utm_campaign, OR enable session-scoped UTM persistence so events fired later in the session inherit the entry-page UTMs.
        DO NOT recommend `custom_source_mappings` for this bucket — there is nothing to map.
        DO NOT recommend reconnecting an integration for this bucket — the events have no source attribution at all.

    - `events_with_unmatched_utm_source`: the event has a `utm_source` value, but it doesn't match any known integration alias (canonical or team-custom).
        Fix: add a `custom_source_mappings` entry, OR fix the upstream UTM tagging to use a recognized value.
        Use `marketing_suggest_utm_mappings` to see the actual unmatched values and which ones look like ad platforms vs organic/direct/test.

    When reporting on a goal's non-integrated count, ALWAYS break it down into these two buckets and propose the correct fix per bucket. Do NOT lump them together.
""").strip()


def _format_goal_line(goal, *, include_id: bool = False) -> str:
    head = f"- id=`{goal.id}` " if include_id else "- "
    line = f"{head}**{goal.name}** (`{goal.kind}`, target=`{goal.target_label}`) — last_30d={goal.last_30d_count}"
    if goal.integrated_count is not None and goal.non_integrated_count is not None:
        line += (
            f", integrated={goal.integrated_count}, "
            f"non_integrated={goal.non_integrated_count} "
            f"(without_utm_source={goal.events_without_utm_source}, "
            f"with_unmatched_utm_source={goal.events_with_unmatched_utm_source}), "
            f"integrated_pct={goal.integrated_pct}%"
        )
    if goal.is_approximate:
        line += f"  (approximate — {goal.approximation_reason or 'approximate count'})"
    if goal.is_misconfigured:
        line += f"  ⚠️ MISCONFIGURED: {goal.misconfig_reason}"
    return line


def _format_data_sources_for_llm(response) -> str:
    connected = [e for e in response.integrations if e.connected]
    lines: list[str] = [
        f"Overall: **{response.overall_status}**. {len(connected)} of {len(response.integrations)} integrations connected.",
        "",
        "REPORTING INSTRUCTION: list each integration individually with its specific missing tables/columns/errors and the `settings_url`. Never agglomerate.",
        "",
    ]
    for entry in response.integrations:
        if not entry.connected:
            lines.append(f"### {entry.display_name} — not connected (settings_url={entry.settings_url})")
            continue
        last_sync = _format_timestamp_for_llm(entry.last_sync_at)
        lines.append(f"### {entry.display_name} — status=`{entry.last_sync_status}`")
        if entry.schemas_url:
            lines.append(f"- schemas_url: {entry.schemas_url}")
        lines.append(f"- last_sync_at: {last_sync}")
        lines.append(
            f"- sync_activity_24h={entry.rows_last_24h} rows processed, "
            f"sync_activity_7d={entry.rows_last_7d} rows processed "
            f"(total throughput across sync jobs, not source-table row count)"
        )
        lines.append(f"- settings_url: {entry.settings_url}")
        if entry.last_error:
            lines.append(f"- last_error: {_sanitize_for_prompt(entry.last_error)}")
        if entry.schema_columns_required_missing:
            lines.append(f"- missing_required_columns: {', '.join(entry.schema_columns_required_missing)}")
        if entry.required_tables:
            table_lines = []
            for t in entry.required_tables:
                if not t.present:
                    table_lines.append(f"`{t.table_name}` (missing)")
                elif not t.should_sync:
                    table_lines.append(f"`{t.table_name}` (disabled)")
                elif t.status == "Failed":
                    table_lines.append(f"`{t.table_name}` (FAILED)")
                else:
                    table_lines.append(f"`{t.table_name}` ({t.status or 'unknown'})")
            lines.append(f"- required_tables: {', '.join(table_lines)}")
        if entry.diagnosis:
            lines.append(f"- diagnosis: {_sanitize_for_prompt(entry.diagnosis, max_len=500)}")
        if entry.fix_suggestion:
            lines.append(f"- fix: {_sanitize_for_prompt(entry.fix_suggestion, max_len=500)}")
        lines.append("")
    if response.issues_summary:
        lines.append("## Issues summary")
        for issue in response.issues_summary:
            lines.append(f"- {issue}")
    return "\n".join(lines)


def _format_explain_goal_for_llm(response) -> str:
    lines: list[str] = [
        f"# Goal '{response.goal_name}' (`{response.kind}`)",
        f"Period: {response.period.date_from} → {response.period.date_to}",
        f"Total: {response.total_count}",
    ]
    if response.integrated_count is not None and response.non_integrated_count is not None:
        lines.append(
            f"Integrated: {response.integrated_count}, "
            f"Non-integrated: {response.non_integrated_count} "
            f"(without_utm_source={response.events_without_utm_source}, "
            f"with_unmatched_utm_source={response.events_with_unmatched_utm_source})"
        )
        lines.append("")
        lines.append(_NON_INTEGRATED_SPLIT_INSTRUCTIONS)

    if response.by_event:
        lines.append("\n## Events")
        for name, count in response.by_event:
            lines.append(f"- {_sanitize_for_prompt(name)}: {count}")
    if response.by_utm_source:
        lines.append("\n## utm_source breakdown")
        for src, count in response.by_utm_source:
            lines.append(f"- {_sanitize_for_prompt(src)}: {count}")
    if response.by_matched_integration:
        lines.append("\n## Matched to integration")
        for integration, count in response.by_matched_integration:
            lines.append(f"- {_sanitize_for_prompt(integration)}: {count}")
    if response.samples:
        lines.append("\n## Sample events (up to 10)")
        for s in response.samples:
            lines.append(
                f"- {s.timestamp} distinct_id={_sanitize_for_prompt(s.distinct_id)} "
                f"utm_source={_sanitize_for_prompt(s.utm_source)!r} "
                f"utm_campaign={_sanitize_for_prompt(s.utm_campaign)!r} "
                f"matched={_sanitize_for_prompt(s.matched_integration)!r}"
            )
    if response.notes:
        lines.append("\n## Notes")
        for note in response.notes:
            lines.append(f"- {note}")
    return "\n".join(lines)


def _format_audit_utm_for_llm(response) -> str:
    lines: list[str] = [
        f"UTM audit: {response.campaigns_with_issues} of {response.total_campaigns} campaigns have issues. "
        f"Total spend at risk: {response.total_spend_at_risk:.2f}.",
    ]
    issue_campaigns = [r for r in response.results if r.issues]
    if issue_campaigns:
        lines.append("\n## Campaigns with issues")
        for r in issue_campaigns[:20]:
            issue_summary = "; ".join(f"{i.severity}: {i.message}" for i in r.issues)
            lines.append(
                f"- **{_sanitize_for_prompt(r.campaign_name)}** ({_sanitize_for_prompt(r.source_name)}) — "
                f"spend={r.spend}, clicks={r.clicks}, events={r.event_count}: {issue_summary}"
            )
    if response.all_utm_events:
        unmatched = [e for e in response.all_utm_events if e.campaign_match == "none" or e.source_match == "none"]
        if unmatched:
            lines.append(f"\n## Unmatched UTM events (top 10 of {len(unmatched)})")
            for e in unmatched[:10]:
                lines.append(
                    f"- utm_source={_sanitize_for_prompt(e.utm_source)!r} "
                    f"utm_campaign={_sanitize_for_prompt(e.utm_campaign)!r} "
                    f"events={e.event_count} src_match={e.source_match} camp_match={e.campaign_match}"
                )
    return "\n".join(lines)


def _format_event_suggestions_for_llm(response) -> str:
    if not response.candidates:
        return (
            "No suitable candidate events found. Try lowering min_count or check that your project has custom events."
        )
    lines: list[str] = [
        f"{len(response.candidates)} candidate events ranked by suitability as conversion goals "
        f"(lookback={response.lookback_days}d):",
        "",
    ]
    for c in response.candidates:
        top_utm = (
            ", ".join(f"{_sanitize_for_prompt(src)}({n})" for src, n in c.top_utm_sources[:3])
            if c.top_utm_sources
            else "(no utm_source samples)"
        )
        flag = " (already a goal)" if c.is_already_a_goal else ""
        lines.append(
            f"- **{_sanitize_for_prompt(c.event_name)}**{flag} — score={c.suggestion_score}, "
            f"30d_count={c.last_30d_count}, users={c.distinct_users_30d}, "
            f"utm_source_pct={c.pct_with_utm_source}%, utm_campaign_pct={c.pct_with_utm_campaign}%, "
            f"top_utm=[{top_utm}]"
        )
        # Built from numeric stats today, but sanitize to stay safe if that changes.
        lines.append(f"    reason: {_sanitize_for_prompt(c.suggestion_reason, max_len=400)}")
    return "\n".join(lines)


def _format_utm_mapping_suggestions_for_llm(response) -> str:
    window = f"the last {response.lookback_days_used} days"
    lines: list[str] = [
        f"Lookback window: {window}.",
        f"Total events with utm_source in {window}: {response.total_events_with_utm_in_window}.",
        f"Total events with UNMATCHED utm_source in {window}: {response.total_unmatched_events_in_window}.",
        "",
        "REPORTING INSTRUCTIONS for the assistant:",
        "- DO NOT run a SQL query for this — `full_utm_source_catalogue` below already lists every utm_source value with counts and integration matches.",
        "- ONLY report values that appear in `full_utm_source_catalogue` or `raw_unmatched_samples`. DO NOT invent canonical variants — those are already mapped canonically (see `current_mappings`).",
        "- Many unmatched values are NOT ad platforms (organic, direct, test, newsletter, partner, twitter without a Twitter Ads integration). Don't suggest mapping those — recommend leaving them as non-integrated.",
        "- Always qualify with the lookback window. Never say 'no UTMs ever' unless 1095+ days were checked.",
        "",
    ]

    # Full catalogue first — this is the primary signal for the LLM.
    if response.full_utm_source_catalogue:
        lines.append(
            f"## All utm_source values seen in {window} (top {len(response.full_utm_source_catalogue)} by event count)"
        )
        lines.append("| utm_source | events | matched? |")
        lines.append("|---|---|---|")
        for entry in response.full_utm_source_catalogue:
            if entry.matched_integration_display_name:
                match_col = f"✅ {entry.matched_integration_display_name}"
            elif entry.suggested_integration:
                match_col = f"≈ likely {entry.suggested_integration} (alias token)"
            else:
                match_col = "❌ unmatched"
            lines.append(f"| `{_sanitize_for_prompt(entry.raw_utm_source)}` | {entry.event_count} | {match_col} |")
        lines.append("")

    # Suggestions: value's token matches a known alias, ready to apply
    if response.source_suggestions:
        lines.append(f"## Suggestions ({len(response.source_suggestions)})")
        for s in response.source_suggestions:
            lines.append(
                f"- raw `{_sanitize_for_prompt(s.raw_utm_source)}` → **{s.suggested_target_display_name}** "
                f"(events_in_window={s.event_count_30d})"
            )
            # `reason` embeds the raw utm_source value — sanitize.
            lines.append(f"    {_sanitize_for_prompt(s.reason, max_len=400)}")
        lines.append("")
    else:
        lines.append("## Suggestions: none")
        lines.append("")

    # Raw catalogue: every unmatched value we saw, with the alias-token hint if any
    if response.raw_unmatched_samples:
        lines.append(
            f"## Raw unmatched utm_source values seen in {window} "
            f"(top {len(response.raw_unmatched_samples)} by event count)"
        )
        lines.append(
            "These are the actual values arriving on events. Many will be organic/direct/test "
            "and should NOT be mapped to ad platforms. Use this list to give a SPECIFIC answer."
        )
        for s in response.raw_unmatched_samples:
            hint = (
                f" — likely {s.suggested_integration} (alias token)"
                if s.suggested_integration
                else " — no alias match (likely organic/direct/test, or a typo to judge yourself)"
            )
            lines.append(f"- `{_sanitize_for_prompt(s.raw_utm_source)}` ({s.event_count} events){hint}")
        lines.append("")

    # Current mappings: canonical + team-custom
    if response.current_mappings:
        canonical = [m for m in response.current_mappings if m.source == "canonical"]
        team_custom = [m for m in response.current_mappings if m.source == "team_custom"]
        lines.append("## Already-active mappings (canonical aliases hardcoded by PostHog)")
        # Group canonical by target for readability
        by_target: dict[str, list[str]] = {}
        for m in canonical:
            by_target.setdefault(m.target_display_name, []).append(m.raw_utm_source)
        for target, raws in sorted(by_target.items()):
            lines.append(f"- **{target}**: {', '.join(sorted(raws))}")
        if team_custom:
            lines.append("")
            lines.append("## Team-custom mappings already configured")
            tc_by_target: dict[str, list[str]] = {}
            for m in team_custom:
                tc_by_target.setdefault(m.target_display_name, []).append(m.raw_utm_source)
            for target, raws in sorted(tc_by_target.items()):
                lines.append(f"- **{target}**: {', '.join(sorted(raws))}")
        else:
            lines.append("")
            lines.append("## Team-custom mappings already configured: none")
        lines.append("")

    if response.notes:
        lines.append("## Notes")
        for note in response.notes:
            lines.append(f"- {note}")
    return "\n".join(lines)
