import uuid

from django.core.cache import cache

import structlog
from rest_framework.exceptions import ValidationError

from posthog.errors import InternalCHQueryError
from posthog.event_usage import EventSource
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.llm.system_one_client import system_one_configured
from posthog.models import Team, User

from products.workflows.backend.facade.contracts import (
    BuiltSuggestion,
    DataSuggestion,
    DataSuggestionBuildFailed,
    DataSuggestionNotFound,
    DataSuggestionsResult,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.presentation.views.graph_validation import validate_graph
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer
from products.workflows.backend.services.data_suggestions import team_context
from products.workflows.backend.services.data_suggestions.builder import (
    BuildContext,
    BuiltWorkflow,
    build_workflow,
    clean_copy,
)
from products.workflows.backend.services.data_suggestions.event_volume import weekly_counts
from products.workflows.backend.services.data_suggestions.planner import (
    MAX_PLANNED_STEPS,
    IdeaContext,
    StepsContext,
    WorkflowIdea,
    plan_steps,
    suggest_ideas,
)
from products.workflows.backend.services.data_suggestions.ranking import (
    FLAT_WEIGHTS,
    STAGE_WEIGHTS,
    guess_stage,
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
FAILURE_CACHE_TTL_SECONDS = 5 * 60
# Longer than the slowest run, so a crashed worker cannot block a team for good.
_GENERATION_LOCK_SECONDS = 5 * 60
MAX_SUGGESTIONS = 3
_PROMPT_EVENTS_LIMIT = 60
_GENERATION_ERRORS = (
    StageClassificationFailed,
    InternalCHQueryError,
    ClickHouseQueryTimeOut,
    ClickHouseAtCapacity,
    ClickHouseQueryMemoryLimitExceeded,
)


def get_data_suggestions(*, team: Team, user: User, refresh: bool = False) -> DataSuggestionsResult:
    if team.organization.is_ai_data_processing_approved is not True:
        return DataSuggestionsResult(status="ai_not_approved", suggestions=())
    # Without Jev the ranking cannot tell a sign-up from routine usage, so no suggestions are made.
    if not system_one_configured():
        return DataSuggestionsResult(status="unavailable", suggestions=())

    key = _cache_key(team)
    cached = cache.get(key)
    if not refresh and isinstance(cached, DataSuggestionsResult):
        return cached

    # Visits that arrive while a run is going would each repeat the queries and the model calls.
    lock = _generation_lock_key(team)
    if not cache.add(lock, True, _GENERATION_LOCK_SECONDS):
        return DataSuggestionsResult(status="unavailable", suggestions=())
    try:
        result = _generate(team=team, user=user)
        # A failed refresh keeps the working suggestions, so builds that use their ids still find them.
        if result.status != "ready" and isinstance(cached, DataSuggestionsResult) and cached.status == "ready":
            return cached
        # An empty answer often means the team's events have not arrived yet, so it is retried as soon as a failure.
        ttl = CACHE_TTL_SECONDS if result.status == "ready" and result.suggestions else FAILURE_CACHE_TTL_SECONDS
        # Written before the lock is released, so the next visit reads it instead of starting another run.
        cache.set(key, result, ttl)
        return result
    finally:
        cache.delete(lock)


def has_cached_data_suggestions(*, team: Team) -> bool:
    return isinstance(cache.get(_cache_key(team)), DataSuggestionsResult)


def build_data_suggestion(*, team: Team, user: User, suggestion_id: str) -> BuiltSuggestion:
    """Plans the steps of one suggestion and returns a validated draft workflow. Nothing is saved here."""
    if team.organization.is_ai_data_processing_approved is not True:
        raise DataSuggestionNotFound()
    suggestion = _cached_suggestion(team, suggestion_id)
    if suggestion is None:
        raise DataSuggestionNotFound()

    idea = WorkflowIdea(
        name=suggestion.name,
        description=suggestion.description,
        reason=suggestion.reason,
        trigger_event=suggestion.trigger_event,
        step_outline=list(suggestion.step_outline),
    )
    email_templates = team_context.email_templates(team)
    slack_integration_id = team_context.slack_integration_id(team)
    step_templates = tuple(list_step_templates(team))
    channels = team_context.channels(team)
    events = team_context.recent_event_names(team, exclude=set())[:_PROMPT_EVENTS_LIMIT]
    plan = plan_steps(
        team=team,
        user=user,
        context=StepsContext(
            idea=idea,
            email_templates=email_templates,
            step_templates=step_templates,
            events=tuple(events),
            channels=channels,
            has_slack=slack_integration_id is not None,
        ),
    )
    if plan is None:
        raise DataSuggestionBuildFailed()

    built = build_workflow(
        idea,
        plan,
        BuildContext(
            allowed_events=frozenset({suggestion.trigger_event, *events}),
            step_template_ids=frozenset(template.template_id for template in step_templates),
            channels=channels,
            email_templates={str(template.id): template for template in email_templates},
            sender=team_context.email_sender(team),
            slack_integration_id=slack_integration_id,
        ),
    )
    if built is None or not _is_valid(team, built):
        raise DataSuggestionBuildFailed()
    return BuiltSuggestion(workflow=built.workflow, uses_saved_template=built.uses_saved_template)


def _cache_key(team: Team) -> str:
    # The cache holds pickled DataSuggestionsResult objects, so bump the version when that class changes or moves.
    # A team's first workflow moves it from the new to the existing ranking, so the two get separate entries.
    audience = "new" if _is_new_to_workflows(team) else "existing"
    return f"workflows:data_suggestions:v4:{team.id}:{audience}"


def _is_new_to_workflows(team: Team) -> bool:
    return not HogFlow.objects.filter(team_id=team.id).exclude(status="archived").exists()


def _generation_lock_key(team: Team) -> str:
    return f"workflows:data_suggestions:generating:{team.id}"


def _cached_suggestion(team: Team, suggestion_id: str) -> DataSuggestion | None:
    cached = cache.get(_cache_key(team))
    if not isinstance(cached, DataSuggestionsResult):
        return None
    return next((item for item in cached.suggestions if item.id == suggestion_id), None)


def _generate(*, team: Team, user: User) -> DataSuggestionsResult:
    try:
        return _suggest(team=team, user=user)
    except _GENERATION_ERRORS:
        return DataSuggestionsResult(status="unavailable", suggestions=())


def _suggest(*, team: Team, user: User) -> DataSuggestionsResult:
    used_events = team_context.used_trigger_events(team)
    is_new = _is_new_to_workflows(team)
    counts = weekly_counts(team, team_context.recent_event_names(team, exclude=used_events))
    if not counts:
        return DataSuggestionsResult(status="ready", suggestions=())

    # Jev classifies a capped number of events. The existing triggers go first, because the covered stages come
    # from them, and they take at most half of the cap so that candidate events still get classified.
    used = sorted(used_events)[: MAX_CLASSIFIED_EVENTS // 2]
    candidates = select_prompt_events(counts, limit=MAX_CLASSIFIED_EVENTS - len(used))
    jev_stages = classify_event_stages(team_id=team.id, event_names=used + [name for name, _ in candidates])
    covered_stages = {jev_stages.get(name, guess_stage(name)) for name in used_events} - {"other"}
    weights = STAGE_WEIGHTS if is_new else FLAT_WEIGHTS
    prompt_events = [
        (name, count)
        for name, count in select_prompt_events(
            counts, limit=_PROMPT_EVENTS_LIMIT * 2, stages=jev_stages, weights=weights
        )
        if jev_stages.get(name, guess_stage(name)) not in covered_stages
    ][:_PROMPT_EVENTS_LIMIT]
    if not prompt_events:
        return DataSuggestionsResult(status="ready", suggestions=())
    offered = {name for name, _ in prompt_events}
    ideas = suggest_ideas(
        team=team,
        user=user,
        context=IdeaContext(
            events=tuple(prompt_events),
            stages=jev_stages,
            prioritize_onboarding=is_new,
            channels=team_context.channels(team),
            has_slack=team_context.slack_integration_id(team) is not None,
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
                weekly_count=counts[idea.trigger_event],
                # Jev judges each event the same way for every customer. An event Jev did not classify is "other".
                stage=jev_stages.get(idea.trigger_event, "other"),
                step_outline=outline,
            )
        )
    ranked = sorted(
        (item for item in suggestions if item.stage not in covered_stages),
        key=lambda item: suggestion_score(item.stage, item.weekly_count, weights),
        reverse=True,
    )
    return DataSuggestionsResult(
        status="ready",
        suggestions=tuple(pick_one_per_stage(ranked, stage_of=lambda item: item.stage, limit=MAX_SUGGESTIONS)),
    )


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
