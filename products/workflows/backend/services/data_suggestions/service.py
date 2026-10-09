import math
import uuid
from typing import Any, Literal

from django.core.cache import cache

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import HogQLQueryResponse, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.models import EventDefinition, Team, User
from posthog.models.integration import Integration

from products.messaging.backend.facade.api import list_email_templates
from products.workflows.backend.facade.contracts import DataSuggestionBuildFailed, DataSuggestionNotFound
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.presentation.views.graph_validation import validate_graph
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer
from products.workflows.backend.services.data_suggestions.brand import fetch_brand_kit, resolve_brand_domain
from products.workflows.backend.services.data_suggestions.builder import (
    BuildContext,
    BuiltWorkflow,
    EmailSender,
    build_workflow,
    clean_copy,
)
from products.workflows.backend.services.data_suggestions.planner import (
    MAX_PLANNED_STEPS,
    Channel,
    IdeaContext,
    OutlineKind,
    StepsContext,
    WorkflowIdea,
    plan_steps,
    suggest_ideas,
)
from products.workflows.backend.services.data_suggestions.ranking import (
    LifecycleStage,
    pick_one_per_stage,
    select_prompt_events,
    suggestion_score,
)
from products.workflows.backend.services.data_suggestions.stages import (
    MAX_CLASSIFIED_EVENTS,
    StageClassificationFailed,
    classify_event_stages,
)
from products.workflows.backend.services.hog_flow_templates import list_step_templates

logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
# A failed run waits this long before it tries again, so an outage does not rerun the queries on every visit.
FAILURE_CACHE_TTL_SECONDS = 30 * 60
# Above this many events a week the counts are sampled. The estimate itself reads 1 in 100 events.
_FULL_SCAN_MAX_WEEKLY_EVENTS = 20_000_000
_ESTIMATE_SAMPLE_DENOMINATOR = 100
_COUNT_TIMEOUT_SECONDS = 30
MAX_SUGGESTIONS = 3
_EVENT_DEFINITIONS_LIMIT = 300
_PROMPT_EVENTS_LIMIT = 60
_TEMPLATES_LIMIT = 20
# PostHog's own events that mark a real moment, unlike the generic `$` events the planner must skip.
_ALLOWED_POSTHOG_EVENTS = frozenset({"$conversation_ticket_created"})

DataSuggestionsStatus = Literal["ready", "ai_not_approved", "unavailable"]


@frozen
class DataSuggestion:
    id: str
    name: str
    description: str
    reason: str
    trigger_event: str
    weekly_count: int
    stage: LifecycleStage
    step_outline: tuple[OutlineKind, ...]


@frozen
class DataSuggestionsResult:
    status: DataSuggestionsStatus
    suggestions: tuple[DataSuggestion, ...]


@frozen
class BuiltSuggestion:
    workflow: dict[str, Any]
    uses_saved_template: bool
    brand_site_name: str | None


def get_data_suggestions(*, team: Team, user: User, refresh: bool = False) -> DataSuggestionsResult:
    if team.organization.is_ai_data_processing_approved is not True:
        return DataSuggestionsResult(status="ai_not_approved", suggestions=())

    key = _cache_key(team)
    if not refresh:
        cached = cache.get(key)
        if isinstance(cached, DataSuggestionsResult):
            return cached

    try:
        result = _suggest(team=team, user=user)
    except StageClassificationFailed:
        result = DataSuggestionsResult(status="unavailable", suggestions=())
    cache.set(key, result, CACHE_TTL_SECONDS if result.status == "ready" else FAILURE_CACHE_TTL_SECONDS)
    return result


def build_data_suggestion(*, team: Team, user: User, suggestion_id: str) -> BuiltSuggestion:
    """Plans the steps of one suggestion and returns a validated draft workflow. Nothing is saved here."""
    if team.organization.is_ai_data_processing_approved is not True:
        raise DataSuggestionNotFound()
    cached = cache.get(_cache_key(team))
    suggestion = (
        next((item for item in cached.suggestions if item.id == suggestion_id), None)
        if isinstance(cached, DataSuggestionsResult)
        else None
    )
    if suggestion is None:
        raise DataSuggestionNotFound()

    idea = WorkflowIdea(
        name=suggestion.name,
        description=suggestion.description,
        reason=suggestion.reason,
        trigger_event=suggestion.trigger_event,
        stage=suggestion.stage,
        step_outline=list(suggestion.step_outline),
    )
    email_templates = _email_templates(team)
    slack_integration_id = _slack_integration_id(team)
    step_templates = list_step_templates(team)
    channels = _channels(team)
    events = _recent_event_names(team, exclude=set())[:_PROMPT_EVENTS_LIMIT]
    plan = plan_steps(
        team=team,
        user=user,
        context=StepsContext(
            idea=idea,
            email_templates=tuple(
                (template_id, str(content.get("_name", "")), str(content.get("subject", "")))
                for template_id, content in email_templates.items()
            ),
            step_templates=tuple(
                (template.template_id, template.name, template.description) for template in step_templates
            ),
            events=tuple(events),
            channels=channels,
            has_slack=slack_integration_id is not None,
        ),
    )
    if plan is None:
        raise DataSuggestionBuildFailed()
    needs_brand = any(step.type == "email" and not step.email_template_id for step in plan.steps)
    brand_domain = resolve_brand_domain(team) if needs_brand else None
    brand = fetch_brand_kit(brand_domain) if brand_domain else None

    built = build_workflow(
        idea,
        plan,
        BuildContext(
            allowed_events=frozenset({suggestion.trigger_event, *events}),
            step_template_ids=frozenset(template.template_id for template in step_templates),
            channels=channels,
            email_templates=email_templates,
            sender=_email_sender(team),
            slack_integration_id=slack_integration_id,
            brand=brand,
        ),
    )
    if built is None or not _is_valid(team, built):
        raise DataSuggestionBuildFailed()
    return BuiltSuggestion(
        workflow=built.workflow,
        uses_saved_template=built.uses_saved_template,
        brand_site_name=brand.site_name if brand else None,
    )


def _cache_key(team: Team) -> str:
    return f"workflows:data_suggestions:v3:{team.id}"


def _suggest(*, team: Team, user: User) -> DataSuggestionsResult:
    used_events = _used_trigger_events(team)
    weekly_counts = _weekly_counts(team, exclude=used_events)
    if not weekly_counts:
        return DataSuggestionsResult(status="ready", suggestions=())

    candidates = select_prompt_events(weekly_counts, limit=MAX_CLASSIFIED_EVENTS)
    jev_stages = classify_event_stages(team_id=team.id, event_names=[name for name, _ in candidates])
    prompt_events = select_prompt_events(weekly_counts, limit=_PROMPT_EVENTS_LIMIT, stages=jev_stages)
    if not prompt_events:
        return DataSuggestionsResult(status="ready", suggestions=())
    offered = {name for name, _ in prompt_events}
    ideas = suggest_ideas(
        team=team,
        user=user,
        context=IdeaContext(
            events=tuple(prompt_events),
            stages=jev_stages,
            channels=_channels(team),
            has_slack=_slack_integration_id(team) is not None,
        ),
    )
    if not ideas:
        return DataSuggestionsResult(status="unavailable", suggestions=())

    suggestions: list[DataSuggestion] = []
    seen_events: set[str] = set()
    for idea in ideas:
        outline = tuple(idea.step_outline[:MAX_PLANNED_STEPS])
        # The model can only pick from the listed events; anything else is a made-up name.
        if idea.trigger_event not in offered or idea.trigger_event in seen_events or not outline:
            continue
        seen_events.add(idea.trigger_event)
        suggestions.append(
            DataSuggestion(
                id=str(uuid.uuid4()),
                name=clean_copy(idea.name)[:50],
                description=clean_copy(idea.description),
                reason=clean_copy(idea.reason),
                trigger_event=idea.trigger_event,
                weekly_count=weekly_counts[idea.trigger_event],
                # Jev's stage wins: it judges each event the same way for every customer.
                stage=jev_stages.get(idea.trigger_event, idea.stage),
                step_outline=outline,
            )
        )
    ranked = sorted(suggestions, key=lambda item: suggestion_score(item.stage, item.weekly_count), reverse=True)
    return DataSuggestionsResult(
        status="ready",
        suggestions=tuple(pick_one_per_stage(ranked, stage_of=lambda item: item.stage, limit=MAX_SUGGESTIONS)),
    )


def _channels(team: Team) -> frozenset[Channel]:
    kinds = set(Integration.objects.filter(team_id=team.id).values_list("kind", flat=True))
    channels: set[Channel] = set()
    if "twilio" in kinds:
        channels.add("sms")
    if kinds & {"apns", "firebase"}:
        channels.add("push")
    return frozenset(channels)


def _slack_integration_id(team: Team) -> int | None:
    return (
        Integration.objects.filter(team_id=team.id, kind="slack")
        .order_by("created_at")
        .values_list("id", flat=True)
        .first()
    )


def _used_trigger_events(team: Team) -> set[str]:
    used: set[str] = set()
    for trigger in HogFlow.objects.filter(team_id=team.id).exclude(status="archived").values_list("trigger", flat=True):
        filters = (trigger or {}).get("filters") or {}
        for event in filters.get("events") or []:
            if isinstance(event, dict) and isinstance(event.get("id"), str):
                used.add(event["id"])
    return used


def _recent_event_names(team: Team, *, exclude: set[str]) -> list[str]:
    return [
        name
        for name in EventDefinition.objects.filter(team_id=team.id)
        .order_by("-last_seen_at")
        .values_list("name", flat=True)[:_EVENT_DEFINITIONS_LIMIT]
        if name not in exclude and (not name.startswith("$") or name in _ALLOWED_POSTHOG_EVENTS)
    ]


def _weekly_counts(team: Team, *, exclude: set[str]) -> dict[str, int]:
    names = _recent_event_names(team, exclude=exclude)
    if not names:
        return {}
    # Small teams get exact counts, since a quiet event could vanish from a sample. Large teams only need the
    # ranking, so a sample keeps the scan at about the size of a small team's.
    sample_denominator = max(1, math.ceil(_estimated_weekly_events(team) / _FULL_SCAN_MAX_WEEKLY_EVENTS))
    query = parse_select(
        """
        SELECT event, count() AS weekly_count
        FROM events
        WHERE timestamp >= now() - INTERVAL 7 DAY AND event IN {names}
        GROUP BY event
        ORDER BY weekly_count DESC
        """,
        placeholders={"names": ast.Tuple(exprs=[ast.Constant(value=name) for name in names])},
    )
    if sample_denominator > 1 and isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(sample_denominator)
    response = _run_count(team, query, "workflows_data_suggestions_counts")
    return {str(row[0]): int(row[1]) * sample_denominator for row in response.results or [] if int(row[1]) > 0}


def _estimated_weekly_events(team: Team) -> int:
    query = parse_select("SELECT count() FROM events WHERE timestamp >= now() - INTERVAL 7 DAY")
    if isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(_ESTIMATE_SAMPLE_DENOMINATOR)
    response = _run_count(team, query, "workflows_data_suggestions_volume")
    rows = response.results or []
    return int(rows[0][0]) * _ESTIMATE_SAMPLE_DENOMINATOR if rows else 0


def _sample(denominator: int) -> ast.SampleExpr:
    return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=denominator)))


def _run_count(team: Team, query: ast.SelectQuery | ast.SelectSetQuery, query_type: str) -> HogQLQueryResponse:
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)
    return execute_hogql_query(
        query=query,
        team=team,
        query_type=query_type,
        settings=HogQLGlobalSettings(max_execution_time=_COUNT_TIMEOUT_SECONDS),
    )


def _email_templates(team: Team) -> dict[str, dict]:
    return {
        str(template.id): {**template.email, "_name": template.name}
        for template in list_email_templates(team.id, limit=_TEMPLATES_LIMIT)
    }


def _email_sender(team: Team) -> EmailSender | None:
    for integration in Integration.objects.filter(team_id=team.id, kind="email").order_by("created_at"):
        config = integration.config or {}
        if config.get("verified") is True and config.get("email"):
            return EmailSender(
                integration_id=integration.id, email=str(config["email"]), name=str(config.get("name") or "")
            )
    return None


def _is_valid(team: Team, built: BuiltWorkflow) -> bool:
    # The draft leaves credentials, channels and filters blank for the team, so it is checked the way the editor
    # saves a draft. The graph wiring is checked in full, and enabling the workflow later validates every step.
    serializer = HogFlowSerializer(
        data={**built.workflow, "status": "draft"},
        context={"team_id": team.id, "get_team": lambda: team, "is_draft": True, "event_source": EventSource.WEB},
    )
    try:
        validate_graph(built.workflow["actions"], built.workflow["edges"])
        serializer.is_valid(raise_exception=True)
    except ValidationError as error:
        logger.info("workflows.data_suggestions.invalid_workflow", team_id=team.id, errors=str(error.detail)[:500])
        return False
    return True
