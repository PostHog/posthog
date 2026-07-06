from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Optional, Union

from django.db.models import F, Q

import structlog

from posthog.schema import CachedTeamTaxonomyQueryResponse, SubscriptionAIPromptMaxLength, TeamTaxonomyQuery

from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import EventDefinition, EventProperty, PropertyDefinition, Team, User
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.security.llm_prompt_sanitization import sanitize_user_text

from products.exports.backend.temporal.subscriptions.ai_subscription.prompts import (
    EVENT_SELECTION_PROMPT,
    EVENT_SELECTION_PROMPT_NAME,
    PLAN_GENERATION_PROMPT,
    PLANNER_PROMPT_NAME,
    render_prompt,
    resolve_prompt,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    EnrichedPromptSpec,
    QueryPlan,
    RelevantEvents,
)

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)


# Single source of truth lives in the generated schema (frontend/src/queries/schema/schema-general.ts),
# so the backend limit and the frontend's cannot drift. Read the field default rather than
# instantiating: the generated RootModel carries a Field() default, which the pydantic mypy plugin
# treats as a required __init__ arg.
PROMPT_MAX_LENGTH: int = int(SubscriptionAIPromptMaxLength.model_fields["root"].default)
EVENT_NAMES_SAMPLE_LIMIT = 20
# bounds the Postgres scan + context size for the dormant-events list
NO_DATA_EVENT_NAMES_LIMIT = 25
# "Dormant" is a fixed, long-horizon signal independent of the report window: an event not seen in this
# many days is worth flagging so the planner doesn't fabricate it, regardless of how short a given run's
# analysis window is.
NO_DATA_LOOKBACK_DAYS = 30
PERSON_PROPERTY_NAMES_LIMIT = 30
EVENT_NAME_MAX_LENGTH = 120
# The top-events list is volume-ranked, so a targeted request ("how are exports doing?") never surfaces
# the niche, low-volume events it needs. A first LLM pass picks the events relevant to the prompt from the
# project's vocabulary (capped); their property schema is then injected — the planner otherwise can't
# reference events, or their properties, it can't see.
CANDIDATE_EVENTS_LIMIT = 500
# Ceiling on events whose schema is injected into the planner. Scaled up alongside the 25-step query-plan
# cap: a metric-heavy prompt can legitimately span many distinct events, and starving the planner of an
# event the prompt names forces it to guess. Bounded by EVENT_PROPERTIES_PER_EVENT_LIMIT so the injected
# schema stays a few thousand property names at most.
RELEVANT_EVENTS_LIMIT = 100
EVENT_PROPERTIES_PER_EVENT_LIMIT = 15

DEFAULT_PLANNER_MODEL = "gpt-4.1"
DEFAULT_SYNTHESIS_MODEL = "gpt-4.1"
_PLANNER_LLM_TIMEOUT_SECONDS = 90.0
_EVENT_SELECTION_LLM_TIMEOUT_SECONDS = 30.0


class PromptRejectedError(ValueError):
    pass


@dataclass(frozen=True)
class ReportWindow:
    """Code-computed, timezone-aware analysis bounds for a report run.

    `start`/`end` are tz-aware in the team's timezone so the planner never has to do timezone math
    in HogQL. The half-open convention is `timestamp >= start AND timestamp < end` — `start_literal`/
    `end_literal` render the bounds as `YYYY-MM-DD HH:MM:SS` (project-tz wall clock, no offset) for
    both the planner context and the query filter. HogQL resolves a bare datetime literal against the
    project timezone, so the offset is implied; this also keeps the filter on the stricter, faster
    `toDateTime` path rather than the best-effort parser an offset suffix would force.

    `compare_start` is the equal-length period immediately before the window, so a period-over-period
    query filters the wider `[compare_start, end)` range and splits at `start`. It's cadence-relative
    for free: a daily window compares today to yesterday, a weekly one this week to last week.
    """

    start: datetime
    end: datetime

    @property
    def start_literal(self) -> str:
        return self.start.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def end_literal(self) -> str:
        return self.end.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def compare_start(self) -> datetime:
        return self.start - (self.end - self.start)

    @property
    def compare_start_literal(self) -> str:
        return self.compare_start.strftime("%Y-%m-%d %H:%M:%S")


def _in_tz(dt: datetime, tz: tzinfo) -> datetime:
    """Normalise to `tz`. Naive inputs are assumed UTC (Django stores tz-aware UTC datetimes, but
    management commands / tests may hand us a naive value)."""
    return (dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)).astimezone(tz)


def compute_report_window(
    team: Team,
    last_successful_delivery_at: Optional[datetime],
    now: datetime,
    window_days: int,
) -> ReportWindow:
    """Compute the `[start, end)` analysis window for a report run, timezone-aware in the team's tz.

    `end` is the run's "now"; `start` is the last SUCCESSFUL delivery's `finished_at` ("since last
    send"), falling back to `end - window_days` when there's no prior successful delivery. This is
    gap-free modulo the prior run's own generation+send latency (its `finished_at` trails its window
    `end` by that much), which is seconds to low minutes and errs toward re-covering rather than
    dropping data. Both bounds are returned in the team timezone. Pure (no DB / no `datetime.now`) so
    it's unit-testable — callers resolve `last_successful_delivery_at` and `now` and pass them in.
    """
    tz = team.timezone_info
    end = _in_tz(now, tz)

    if last_successful_delivery_at is not None:
        # "Since last send": a re-fire shortly after a successful delivery yields a small window (and
        # a short report) because there's genuinely little new data — we don't pad it back to
        # `window_days`, which would double-report data already sent.
        start = _in_tz(last_successful_delivery_at, tz)
        # A clock skew or a stale finished_at could land start after end; clamp to the fallback
        # window so we never hand the planner an inverted range.
        if start >= end:
            start = end - timedelta(days=window_days)
    else:
        start = end - timedelta(days=window_days)

    return ReportWindow(start=start, end=end)


def sanitize_prompt(raw: str | None) -> str:
    if not raw or not raw.strip():
        raise PromptRejectedError("Prompt is empty.")
    if len(raw.strip()) > PROMPT_MAX_LENGTH:
        raise PromptRejectedError(f"Prompt exceeds {PROMPT_MAX_LENGTH} characters.")

    cleaned = sanitize_user_text(raw, max_len=PROMPT_MAX_LENGTH)
    if not cleaned:
        raise PromptRejectedError("Prompt is empty.")

    return cleaned


def _top_event_names(team: Team, limit: int) -> list[str]:
    query = TeamTaxonomyQuery(limit=limit)
    response = TeamTaxonomyQueryRunner(query, team).run(
        ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS,
    )
    if not isinstance(response, CachedTeamTaxonomyQueryResponse):
        return []
    # Event names are user-controlled (project tokens are public — anyone can fire
    # events with arbitrary names). Sanitize so an attacker can't seed the LLM
    # context with prompt-injection payloads via crafted event names.
    sanitized = (sanitize_user_text(item.event, EVENT_NAME_MAX_LENGTH) for item in response.results)
    return [name for name in sanitized if name]


def _no_data_event_names(team: Team, limit: int) -> list[str]:
    # Ground truth for "events with no data" lives in the event-definitions taxonomy, not the events
    # table (which only contains events that fired). An event whose `last_seen_at` predates the dormancy
    # cutoff — or was never seen — is treated as dormant. `last_seen_at` is maintained on ingestion so it
    # can lag slightly, but it's the authoritative taxonomy signal and stops the LLM fabricating a
    # plausible list of dormant events from its general knowledge of PostHog event names. The cutoff is a
    # fixed lookback, decoupled from the report window: dormancy is a property of the event, not the run.
    cutoff = datetime.now(tz=UTC) - timedelta(days=NO_DATA_LOOKBACK_DAYS)
    names = (
        EventDefinition.objects.filter(team_id=team.pk)
        .filter(Q(last_seen_at__isnull=True) | Q(last_seen_at__lt=cutoff))
        .order_by(F("last_seen_at").desc(nulls_last=True), "name")
        .values_list("name", flat=True)[:limit]
    )
    sanitized = (sanitize_user_text(name, EVENT_NAME_MAX_LENGTH) for name in names)
    return [name for name in sanitized if name]


def _person_property_names(team: Team, limit: int) -> list[str]:
    names = (
        PropertyDefinition.objects.filter(team_id=team.pk, type=PropertyDefinition.Type.PERSON)
        .order_by("name")
        .values_list("name", flat=True)[:limit]
    )
    sanitized = (sanitize_user_text(name, EVENT_NAME_MAX_LENGTH) for name in names)
    return [name for name in sanitized if name]


def _group_type_labels(team: Team) -> list[str]:
    # Map each configured group type to its HogQL virtual-join path (group_0..group_4) so the planner
    # knows what `group_<index>` means for this project (e.g. group_0 = organization). These are joined
    # by the engine automatically when referenced — the planner never writes a JOIN.
    labels: list[str] = []
    for gt in get_group_types_for_project(team.project_id or team.pk):
        name = sanitize_user_text(gt.get("group_type", ""), EVENT_NAME_MAX_LENGTH)
        index = gt.get("group_type_index")
        if name and index is not None:
            labels.append(f"group_{index} = {name}")
    return labels


def _candidate_event_names(team: Team, limit: int) -> dict[str, str]:
    # {sanitized_name: raw_name} for the team's events, most-recently-seen first. Sanitized keys are what
    # the selection LLM sees (event names are user-controlled); raw values feed the EventProperty lookup,
    # which is keyed on the stored name. First raw wins if two names sanitize to the same string.
    raw_names = (
        EventDefinition.objects.filter(team_id=team.pk)
        .order_by(F("last_seen_at").desc(nulls_last=True), "name")
        .values_list("name", flat=True)[:limit]
    )
    candidates: dict[str, str] = {}
    for raw in raw_names:
        clean = sanitize_user_text(raw, EVENT_NAME_MAX_LENGTH)
        if clean and clean not in candidates:
            candidates[clean] = raw
    return candidates


def _select_relevant_events(
    team: Team, user: User, prompt: str, trace_correlation_id: Optional[Union[int, str]] = None
) -> list[str]:
    # Pass 1: the model picks relevant events from the project's vocabulary (vs lexical matching). Returns
    # RAW event names (the EventProperty lookup is keyed on them); any failure degrades to no relevant-events
    # section rather than breaking generation.
    candidates = _candidate_event_names(team, CANDIDATE_EVENTS_LIMIT)
    if not candidates:
        return []

    posthog_properties: dict[str, Union[str, int]] = {"feature": "ai_subscription", "stage": "event_selection"}
    if trace_correlation_id is not None:
        posthog_properties["subscription_id"] = trace_correlation_id
    llm = MaxChatOpenAI(
        model=DEFAULT_PLANNER_MODEL,
        timeout=_EVENT_SELECTION_LLM_TIMEOUT_SECONDS,
        user=user,
        team=team,
        billable=True,
        posthog_properties=posthog_properties,
    ).with_structured_output(RelevantEvents, method="json_schema", include_raw=False)

    rendered_prompt = render_prompt(
        resolve_prompt(team, EVENT_SELECTION_PROMPT_NAME, EVENT_SELECTION_PROMPT),
        {"event_names": "\n".join(candidates), "cleaned_prompt": prompt},
    )

    try:
        result = llm.invoke([("system", rendered_prompt)])
    except Exception:
        logger.warning("ai_subscription.event_selection_failed", team_id=team.id, exc_info=True)
        return []
    if not isinstance(result, RelevantEvents):
        logger.warning("ai_subscription.event_selection_malformed", team_id=team.id)
        return []

    # candidates.get maps the model's sanitized picks back to raw names and drops hallucinations in one step.
    selected: list[str] = []
    seen: set[str] = set()
    for name in result.events:
        raw = candidates.get(name)
        if raw is not None and raw not in seen:
            seen.add(raw)
            selected.append(raw)
            if len(selected) >= RELEVANT_EVENTS_LIMIT:
                break
    return selected


def _event_property_names(team: Team, events: list[str], per_event_limit: int) -> dict[str, list[str]]:
    # One indexed (team, event) query. Without it the planner gets no event-property schema and guesses
    # property names — the top cause of InternalHogQLError.
    if not events:
        return {}
    by_event: dict[str, list[str]] = {}
    rows = (
        EventProperty.objects.filter(team_id=team.pk, event__in=events)
        .order_by("event", "property")
        # DB-tier backstop: a property-heavy event can otherwise pull its entire row set into Python
        # before the per-event cap below applies. Caps total rows read; rows are ordered by event name,
        # so when the budget is hit it favours alphabetically-earlier events (not relevance order).
        .values_list("event", "property")[: len(events) * per_event_limit]
    )
    for event, prop in rows:
        props = by_event.setdefault(event, [])
        if len(props) < per_event_limit:
            props.append(prop)
    return by_event


def build_context_blob(team: Team, window: ReportWindow, relevant_events: Sequence[str] = ()) -> str:
    event_names = _top_event_names(team, EVENT_NAMES_SAMPLE_LIMIT)

    # Team / org names are also user-controlled and end up in the LLM context, so
    # apply the same sanitization as event names.
    team_name = sanitize_user_text(team.name, EVENT_NAME_MAX_LENGTH) or "(unnamed)"
    org_name = sanitize_user_text(team.organization.name, EVENT_NAME_MAX_LENGTH) or "(unnamed)"

    # Exact, code-computed bounds in the project timezone — the planner filters on these literals
    # instead of writing its own `now() - INTERVAL`, so there's no timezone math in HogQL and the
    # window is gap-free run-to-run. Half-open: include `start`, exclude `end`.
    lines = [
        f"- Project: {team_name}",
        f"- Organization: {org_name}",
        f"- Project timezone: {team.timezone}",
        f"- Analysis window start (inclusive, project timezone): {window.start_literal}",
        f"- Analysis window end (exclusive, project timezone): {window.end_literal}",
        f"- Filter timestamps with: timestamp >= toDateTime('{window.start_literal}') "
        f"AND timestamp < toDateTime('{window.end_literal}')",
        f"- Previous-period start (for period-over-period comparisons only, project timezone): "
        f"{window.compare_start_literal}",
    ]
    if event_names:
        lines.append("- Top events: " + ", ".join(event_names))
    else:
        lines.append("- Top events: (none recorded yet)")

    if relevant_events:
        props_by_event = _event_property_names(team, list(relevant_events), EVENT_PROPERTIES_PER_EVENT_LIMIT)
        top_set = set(event_names)
        seen: set[str] = set()
        matched: list[tuple[str, str]] = []  # (raw, clean), deduped on the sanitized name
        for raw in relevant_events:
            clean = sanitize_user_text(raw, EVENT_NAME_MAX_LENGTH)
            if clean and clean not in seen:
                seen.add(clean)
                matched.append((raw, clean))
        # Name only the matches not already shown under "Top events" (avoid repeating them)...
        new_names = [clean for _, clean in matched if clean not in top_set]
        if new_names:
            lines.append("- Events matching your request: " + ", ".join(new_names))
        # ...but inject the property schema for EVERY match, including high-volume events already in
        # "Top events" — that line lists names only, so without this the planner still can't see their
        # properties (e.g. $browser on a matched $pageview).
        for raw, clean in matched:
            clean_props = [
                p for p in (sanitize_user_text(pr, EVENT_NAME_MAX_LENGTH) for pr in props_by_event.get(raw, [])) if p
            ]
            if clean_props:
                lines.append(f"  - `{clean}` properties (use properties.<name>): " + ", ".join(clean_props))

    no_data_events = _no_data_event_names(team, NO_DATA_EVENT_NAMES_LIMIT)
    if no_data_events:
        lines.append(
            f"- Events defined but with no data in the last {NO_DATA_LOOKBACK_DAYS} day(s): "
            + ", ".join(no_data_events)
        )

    person_properties = _person_property_names(team, PERSON_PROPERTY_NAMES_LIMIT)
    if person_properties:
        lines.append(
            "- Person properties (reference as person.properties.<name>, no JOIN needed): "
            + ", ".join(person_properties)
        )

    group_labels = _group_type_labels(team)
    if group_labels:
        lines.append(
            "- Group/account types (reference as group_<index>.properties.<name>, no JOIN needed): "
            + ", ".join(group_labels)
        )
    return "\n".join(lines)


def generate_query_plan(
    *,
    cleaned_prompt: str,
    context_blob: str,
    team: Team,
    user: User,
    trace_correlation_id: Optional[Union[int, str]] = None,
) -> QueryPlan:
    # `user is None` is enforced at the public entry point (`generate_ai_report`)
    # which is the only caller path into here. Don't repeat the check.
    posthog_properties: dict[str, Union[str, int]] = {"feature": "ai_subscription", "stage": "plan"}
    if trace_correlation_id is not None:
        posthog_properties["subscription_id"] = trace_correlation_id
    llm = MaxChatOpenAI(
        model=DEFAULT_PLANNER_MODEL,
        timeout=_PLANNER_LLM_TIMEOUT_SECONDS,
        user=user,
        team=team,
        billable=True,
        posthog_properties=posthog_properties,
    ).with_structured_output(QueryPlan, method="json_schema", include_raw=False)

    rendered_prompt = render_prompt(
        resolve_prompt(team, PLANNER_PROMPT_NAME, PLAN_GENERATION_PROMPT),
        {"context_blob": context_blob, "cleaned_prompt": cleaned_prompt},
    )

    result = llm.invoke([("system", rendered_prompt)])
    if not isinstance(result, QueryPlan):
        raise PromptRejectedError("Planner returned a malformed plan.")
    return result


def build_enriched_prompt(
    *,
    team: Team,
    user: User,
    prompt: Optional[str],
    window: ReportWindow,
    trace_correlation_id: Optional[Union[int, str]] = None,
) -> EnrichedPromptSpec:
    cleaned = sanitize_prompt(prompt)
    relevant_events = _select_relevant_events(team, user, cleaned, trace_correlation_id)
    context_blob = build_context_blob(team, window, relevant_events=relevant_events)
    plan = generate_query_plan(
        cleaned_prompt=cleaned,
        context_blob=context_blob,
        team=team,
        user=user,
        trace_correlation_id=trace_correlation_id,
    )
    return EnrichedPromptSpec(cleaned_prompt=cleaned, context_blob=context_blob, plan=plan)
