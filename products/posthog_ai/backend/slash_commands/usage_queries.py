from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional
from uuid import UUID

import dateutil.parser
import posthoganalytics
from pydantic import ValidationError

from posthog.schema import MaxBillingContext

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.tasks.usage_report import (
    AI_BILLING_EXCLUDED_TOOLS,
    AI_COST_MARKUP_PERCENT,
    CLOUD_REGION_TO_TEAM_ID,
    CLOUD_REGION_TO_URL,
    build_ai_billing_region_filter,
)
from posthog.utils import get_instance_region

from products.posthog_ai.backend.models.assistant import Conversation

if TYPE_CHECKING:
    from posthog.models import Team

# Default free tier limit in credits
DEFAULT_FREE_TIER_CREDITS = 2000

POSTHOG_AI_USAGE_REPORT_ASSISTANT_MESSAGE_TITLE = "PostHog AI usage"

# Default GA launch date - don't count usage before this date
DEFAULT_GA_LAUNCH_DATE = datetime(2025, 11, 17, tzinfo=UTC)

CH_BILLING_SETTINGS = {
    "max_execution_time": 60,  # 1 minute
}


@dataclass(frozen=True)
class AiUsagePeriod:
    label: str
    start: datetime
    end: datetime
    query_start: datetime


def _get_billing_config_payload() -> dict | None:
    """
    Get the billing configuration payload from feature flag.
    Returns None if not available or invalid.

    Feature flag: posthog-ai-billing-free-tier-credits
    Expected payload format:
    {
        "ga_launch_date": "2025-11-17",  # ISO format date string (YYYY-MM-DD)
        "EU": {
            "1": 10000,  # team_id (as string): credits (as int)
            "2": 5000
        },
        "US": {
            "2": 10000
        }
    }
    """
    payload: dict | None = posthoganalytics.get_feature_flag_payload(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog-ai-billing-free-tier-credits", "internal_billing_events"
    )

    if isinstance(payload, dict):
        return payload
    return None


def get_ai_free_tier_credits(team_id: int) -> int:
    """
    Get the AI free tier credits limit for a team.
    Falls back to DEFAULT_FREE_TIER_CREDITS if not configured.
    """
    region = get_instance_region()
    if not region:
        return DEFAULT_FREE_TIER_CREDITS

    payload = _get_billing_config_payload()
    if not payload:
        return DEFAULT_FREE_TIER_CREDITS

    region_config = payload.get(region)
    if not region_config or not isinstance(region_config, dict):
        return DEFAULT_FREE_TIER_CREDITS

    team_id_str = str(team_id)
    if team_id_str in region_config:
        try:
            return int(region_config[team_id_str])
        except (ValueError, TypeError):
            return DEFAULT_FREE_TIER_CREDITS

    return DEFAULT_FREE_TIER_CREDITS


def get_ga_launch_date() -> datetime:
    """
    Falls back to DEFAULT_GA_LAUNCH_DATE if not configured.
    """
    payload = _get_billing_config_payload()
    if not payload:
        return DEFAULT_GA_LAUNCH_DATE

    ga_date_str = payload.get("ga_launch_date")
    if not ga_date_str or not isinstance(ga_date_str, str):
        return DEFAULT_GA_LAUNCH_DATE

    try:
        # Parse ISO format date string (YYYY-MM-DD)
        parsed_date = datetime.fromisoformat(ga_date_str)
        # Ensure it has UTC timezone
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=UTC)
        return parsed_date
    except (ValueError, TypeError):
        return DEFAULT_GA_LAUNCH_DATE


def get_conversation_start_time(conversation_id: UUID) -> Optional[datetime]:
    """Get the start time of a conversation."""
    try:
        # nosemgrep: idor-lookup-without-team (internal AI pipeline, IDs from team-scoped context)
        conversation = Conversation.objects.get(id=conversation_id)
        return conversation.created_at
    except Conversation.DoesNotExist:
        return None


def get_ai_credits(
    team_id: int,
    begin: datetime,
    end: datetime,
    conversation_id: Optional[UUID] = None,
) -> int:
    """
    Calculate AI credits used for a specific team (and optionally a specific conversation) in the given time period.
    """
    # Depending on the region, events are stored in different teams
    # Default to EU (team_id 1) for local dev or unknown regions
    region = get_instance_region()
    region_value = region if region in CLOUD_REGION_TO_TEAM_ID else "EU"
    team_to_query = CLOUD_REGION_TO_TEAM_ID[region_value]

    # Only filter by region in production (EU/US) - local dev events don't have region set.
    # The $group_N index for the `instance` group differs across internal projects,
    # so resolve it from the destination team rather than hard-coding $group_1.
    region_filter_clause = ""
    region_filter_params: dict[str, str] = {}
    if region in CLOUD_REGION_TO_TEAM_ID:
        region_filter = build_ai_billing_region_filter(team_to_query, CLOUD_REGION_TO_URL[region_value])
        if region_filter is None:
            return 0
        region_filter_params = region_filter
        region_filter_clause = "AND JSONExtractString(properties, %(region_group_property)s) = %(region_url)s"

    # Session filter expression for PREWHERE (must NOT use alias)
    session_filter_prewhere = (
        "AND JSONExtractString(properties, '$ai_session_id') = %(session_id)s" if conversation_id else ""
    )

    usage_report_kind = "posthog_ai_credits_for_conversation" if conversation_id else "posthog_ai_credits_for_team"

    with tags_context(
        product=Product.MAX_AI,
        feature=Feature.POSTHOG_AI,
        usage_report=usage_report_kind,
        kind=usage_report_kind,
    ):
        query = f"""
        WITH trace_analysis AS (
            WITH %(excluded_tools)s AS excluded_tools
            SELECT
                trace_id,
                session_id,
                multiIf(
                    length(tool_calls) > 0
                    AND arrayAll(
                        i ->
                            -- tool must be in the excluded list
                            has(excluded_tools, tool_names[i])
                            AND
                            -- if it's search, it must be docs-search
                            if(
                                tool_names[i] = 'search',
                                JSONExtractString(JSONExtractRaw(tool_calls[i], 'args'), 'kind') = 'docs',
                                1
                            ),
                        arrayEnumerate(tool_calls)
                    ),
                    0,  -- all tool calls are excluded → NOT billable
                    1   -- everything else → billable
                ) AS is_billable
            FROM (
                SELECT
                    JSONExtractString(properties, '$ai_trace_id') AS trace_id,
                    JSONExtractString(properties, '$ai_session_id') AS session_id,
                    arrayFlatten(
                        arrayMap(
                            msg -> JSONExtractArrayRaw(msg, 'tool_calls'),
                            -- Only get messages from current turn (after last human message)
                            arraySlice(
                                JSONExtractArrayRaw(
                                    JSONExtractRaw(properties, '$ai_output_state'),
                                    'messages'
                                ),
                                -- Start from the position after the last human message
                                arrayLastIndex(
                                    x -> JSONExtractString(x, 'type') = 'human',
                                    JSONExtractArrayRaw(
                                        JSONExtractRaw(properties, '$ai_output_state'),
                                        'messages'
                                    )
                                ) + 1
                            )
                        )
                    ) AS tool_calls,
                    arrayMap(tc -> JSONExtractString(tc, 'name'), tool_calls) AS tool_names
                FROM events
                PREWHERE
                    team_id = %(team_to_query)s
                    {region_filter_clause}
                    AND timestamp >= %(begin)s
                    AND timestamp < %(end)s
                    AND event = '$ai_trace'
                    {session_filter_prewhere}
            )
        ),
        costs AS (
            SELECT
                customer_team_id,
                trace_id,
                session_id,
                cost_usd
            FROM (
                SELECT
                    JSONExtractInt(properties, 'team_id') AS customer_team_id,
                    JSONExtractString(properties, '$ai_trace_id') AS trace_id,
                    JSONExtractString(properties, '$ai_session_id') AS session_id,
                    toDecimal32OrNull(JSONExtractString(properties, '$ai_total_cost_usd'), 5) AS cost_usd,
                    JSONExtractBool(properties, '$ai_billable') AS ai_billable
                FROM events
                PREWHERE
                    team_id = %(team_to_query)s
                    {region_filter_clause}
                    AND timestamp >= %(begin)s
                    AND timestamp < %(end)s
                    AND event = '$ai_generation'
                    {session_filter_prewhere}
            )
            WHERE
                ai_billable = 1
                AND cost_usd > 0
                AND cost_usd IS NOT NULL
                AND customer_team_id = %(team_id)s
        )
        SELECT toInt64(roundBankers(sum(c.cost_usd * 100 * %(markup_multiplier)s))) AS ai_credits
        FROM costs c
        LEFT JOIN trace_analysis t
            ON c.trace_id = t.trace_id
           AND c.session_id = t.session_id
        WHERE t.is_billable = 1 OR t.trace_id IS NULL
        """

        params: dict[str, int | datetime | float | list[str] | str] = {
            "team_id": team_id,
            "team_to_query": team_to_query,
            "begin": begin,
            "end": end,
            "markup_multiplier": 1 + AI_COST_MARKUP_PERCENT,
            "excluded_tools": AI_BILLING_EXCLUDED_TOOLS,
            **region_filter_params,
        }

        if conversation_id:
            params["session_id"] = str(conversation_id)

        results = sync_execute(query, params, workload=Workload.ONLINE, settings=CH_BILLING_SETTINGS)

    if results and results[0][0] is not None:
        return int(results[0][0])
    return 0


def get_ai_credits_for_team(team_id: int, begin: datetime, end: datetime) -> int:
    """Calculate AI credits used for a specific team in the given time period."""
    return get_ai_credits(team_id, begin, end)


def get_ai_credits_for_conversation(team_id: int, conversation_id: UUID, begin: datetime, end: datetime) -> int:
    """Calculate AI credits used for a specific conversation (trace) in the given time period."""
    return get_ai_credits(team_id, begin, end, conversation_id)


def get_past_month_start() -> datetime:
    """
    Get the start of the past month period (30 days ago), capped at GA launch date.
    """
    now = datetime.now(UTC)
    thirty_days_ago = now - timedelta(days=30)
    ga_launch_date = get_ga_launch_date()
    return max(thirty_days_ago, ga_launch_date)


def _parse_period_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None

    try:
        parsed = dateutil.parser.isoparse(value)
    except (ValueError, TypeError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _build_billing_period(start_value: object, end_value: object) -> tuple[datetime, datetime] | None:
    start = _parse_period_datetime(start_value)
    end = _parse_period_datetime(end_value)

    if start is None or end is None or start >= end:
        return None

    return start, end


def _get_billing_period_from_context(
    billing_context: MaxBillingContext | dict[str, object] | None,
) -> tuple[datetime, datetime] | None:
    if not billing_context:
        return None

    try:
        context = (
            billing_context
            if isinstance(billing_context, MaxBillingContext)
            else MaxBillingContext.model_validate(billing_context)
        )
    except ValidationError:
        return None

    if not context.billing_period:
        return None

    return _build_billing_period(
        context.billing_period.current_period_start,
        context.billing_period.current_period_end,
    )


def _get_billing_period_from_organization(team: "Team") -> tuple[datetime, datetime] | None:
    usage = team.organization.usage
    if not isinstance(usage, dict):
        return None

    period = usage.get("period")
    if not isinstance(period, list) or len(period) < 2:
        return None

    return _build_billing_period(period[0], period[1])


def get_ai_usage_period(team: "Team", billing_context: MaxBillingContext | dict[str, object] | None) -> AiUsagePeriod:
    billing_period = _get_billing_period_from_context(billing_context) or _get_billing_period_from_organization(team)
    if billing_period:
        period_start, period_end = billing_period
        return AiUsagePeriod(
            label="Billing period",
            start=period_start,
            end=period_end,
            query_start=max(period_start, get_ga_launch_date()),
        )

    start = get_past_month_start()
    return AiUsagePeriod(
        label="Past 30 days",
        start=start,
        end=datetime.now(UTC),
        query_start=start,
    )


def format_usage_message(
    conversation_credits: int,
    period_credits: int,
    free_tier_credits: int,
    conversation_start: Optional[datetime] = None,
    usage_period: Optional[AiUsagePeriod] = None,
    include_conversation_line: bool = True,
) -> str:
    """
    Format the usage information into a user-friendly message with a compact layout
    and a simple progress bar against the free tier for the current team_id.

    `include_conversation_line` is False on the sandbox runtime, where per-conversation
    attribution is structurally unavailable (no `$ai_session_id` is stamped), so the
    "Current conversation" line is omitted rather than always showing 0.
    """
    remaining = free_tier_credits - period_credits
    used = period_credits

    # Unicode progress bar (20 segments)
    bar_segments = 20
    # Cap fill for the bar at 20; we'll annotate percentage separately (can exceed 100%)
    fill_ratio = 0 if free_tier_credits <= 0 else max(0.0, min(used / free_tier_credits, 1.0))
    filled = int(round(bar_segments * fill_ratio))
    empty = bar_segments - filled
    bar = f"[{'█' * filled}{'░' * empty}]"
    percent = 0 if free_tier_credits <= 0 else (used / free_tier_credits) * 100

    lines: list[str] = [f"## {POSTHOG_AI_USAGE_REPORT_ASSISTANT_MESSAGE_TITLE}", ""]

    if usage_period is None:
        fallback_start = get_past_month_start()
        usage_period = AiUsagePeriod(
            label="Past 30 days",
            start=fallback_start,
            end=datetime.now(UTC),
            query_start=fallback_start,
        )
    ga_launch_date = get_ga_launch_date()
    ga_cap_active = usage_period.start < ga_launch_date and usage_period.query_start.date() == ga_launch_date.date()
    period_label = f"**{usage_period.label}**"
    if usage_period.label == "Billing period":
        period_label += f" ({usage_period.start.strftime('%Y-%m-%d')} to {usage_period.end.strftime('%Y-%m-%d')})"
    if ga_cap_active:
        period_label += f" (since {ga_launch_date.strftime('%Y-%m-%d')})"

    if include_conversation_line:
        lines.append(f"**Current conversation**: {conversation_credits:,} credits\n")
    lines.append(f"{period_label}: {period_credits:,} credits\n")
    lines.append(f"**Free tier limit**: {free_tier_credits:,} credits\n")

    # Progress bar + percent
    if free_tier_credits > 0:
        pct_label = f"{percent:.0f}% of free tier" if percent <= 999 else "999%+ of free tier"
        lines.append(f"**{usage_period.label} usage**: {bar} {pct_label}\n")

    # Remaining or overage
    if remaining >= 0:
        lines.append(f"**Remaining**: {remaining:,} credits\n")
    else:
        overage = abs(remaining)
        lines.append(f"**Overage**: {overage:,} credits over limit\n")

    # Conversation start (optional context)
    if conversation_start:
        lines.append(f"_Conversation since_: {conversation_start.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n")

    if usage_period.label == "Billing period":
        lines.append(f"_Billing period resets on_: {usage_period.end.strftime('%Y-%m-%d %H:%M UTC')}\n")

    lines.append("")
    if usage_period.label == "Billing period":
        lines.append(
            "_Current conversation resets when you start a new chat; billing period usage resets at the end of this billing period._"
        )
    else:
        lines.append(
            "_Current conversation resets when you start a new chat; past 30 days is rolling usage for this project because billing period information is unavailable._"
        )
    lines.append("_Note: Usage data depends on AI trace ingestion and may lag slightly behind real-time activity._")

    # Add GA cap explanation if active
    if ga_cap_active:
        lines.append(
            f"\n_{usage_period.label} usage is calculated from PostHog AI general availability date ({ga_launch_date.strftime('%b %d, %Y')}) "
            "as usage before this date is not counted._"
        )

    return "\n".join(lines)
