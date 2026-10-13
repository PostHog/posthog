import uuid
import dataclasses
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from django.core.cache import cache

import structlog

from posthog.cloud_utils import is_cloud
from posthog.errors import CH_TRANSIENT_ERRORS, InternalCHQueryError
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.llm.system_one_client import system_one_configured
from posthog.models import Team, User
from posthog.ph_client import get_client
from posthog.utils import get_instance_region

from products.workflows.backend.facade.contracts import (
    BuiltSuggestion,
    DataSuggestion,
    DataSuggestionBuildFailed,
    DataSuggestionNotFound,
    DataSuggestionsResult,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.data_suggestions import team_context
from products.workflows.backend.services.data_suggestions.builder import BuildContext, build_workflow, clean_copy
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

from ee.hogai.utils.feature_flags import is_privacy_mode_enabled

logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
# A failed run waits this long before it tries again, so an outage does not rerun the queries on every visit.
FAILURE_CACHE_TTL_SECONDS = 5 * 60
# Longer than the slowest run, model retries included, so a second run cannot start while the first is alive. Short
# enough that a crashed worker does not block a team for long.
_GENERATION_LOCK_SECONDS = 15 * 60
# A built draft is kept this long, so a retry after a failed save does not pay for another plan.
_BUILD_CACHE_SECONDS = 60 * 60
MAX_SUGGESTIONS = 3
_PROMPT_EVENTS_LIMIT = 60
_GENERATION_ERRORS = (
    StageClassificationFailed,
    InternalCHQueryError,
    ClickHouseQueryTimeOut,
    ClickHouseQueryMemoryLimitExceeded,
    *CH_TRANSIENT_ERRORS,
)

_GENERATING = DataSuggestionsResult(status="generating", suggestions=())
_UNAVAILABLE = DataSuggestionsResult(status="unavailable", suggestions=())


def get_data_suggestions(*, team: Team) -> DataSuggestionsResult:
    """The cards as they are now. This never runs a query or a model, so a read-only caller cannot cause spend."""
    unavailable = _unavailable_reason(team)
    if unavailable is not None:
        return unavailable
    # Checked before the cache, so a refresh in progress reads as generating rather than as the old cards.
    if cache.get(_generation_lock_key(team)) is not None:
        return _GENERATING
    return _read_cache(team) or _UNAVAILABLE


def start_data_suggestions(*, team: Team, refresh: bool, enqueue: Callable[[str], None]) -> DataSuggestionsResult:
    """Returns the cached cards, or starts a background run through `enqueue` and reports that it is generating."""
    unavailable = _unavailable_reason(team)
    if unavailable is not None:
        return unavailable
    cached = _read_cache(team)
    if cached is not None and not refresh:
        return cached
    # Visits that arrive while a run is going would each repeat the queries and the model calls.
    lock_token = str(uuid.uuid4())
    if not cache.add(_generation_lock_key(team), lock_token, _GENERATION_LOCK_SECONDS):
        return _GENERATING
    try:
        enqueue(lock_token)
    except Exception:
        _release_lock(team.id, lock_token)
        logger.exception("workflows.data_suggestions.enqueue_failed", team_id=team.id)
        return _UNAVAILABLE
    return _GENERATING


def has_cached_data_suggestions(*, team: Team) -> bool:
    return _read_cache(team) is not None


def run_data_suggestions(*, team_id: int, user_id: int, lock_token: str) -> None:
    """The background run that `start_data_suggestions` queues. It caches the result and releases the lock."""
    try:
        team = Team.objects.select_related("organization").get(id=team_id)
        user = User.objects.get(id=user_id)
        # Consent or privacy settings can change between the click and the worker picking the run up.
        if _unavailable_reason(team) is not None:
            return
        previous = _read_cache(team)
        with _analytics_client() as analytics_client:
            result = _generate(team=team, user=user, analytics_client=analytics_client)
        # A failed refresh keeps the working suggestions, so builds that use their ids still find them.
        if result.status != "ready" and previous is not None and previous.status == "ready":
            return
        # An empty answer often means the team's events have not arrived yet, so it is retried as soon as a failure.
        ttl = CACHE_TTL_SECONDS if result.status == "ready" and result.suggestions else FAILURE_CACHE_TTL_SECONDS
        # Written before the lock is released, so the next visit reads it instead of starting another run.
        cache.set(_cache_key(team), _to_cache(result), ttl)
    finally:
        _release_lock(team_id, lock_token)


def build_data_suggestion(
    *, team: Team, user: User, suggestion_id: str, is_valid_draft: Callable[[dict[str, Any]], bool]
) -> BuiltSuggestion:
    """Plans the steps of one suggestion and returns a draft workflow that passes `is_valid_draft`.
    Nothing is saved here. A repeated build of the same suggestion returns the first draft without a new plan."""
    if team.organization.is_ai_data_processing_approved is not True:
        raise DataSuggestionNotFound()
    suggestion = _cached_suggestion(team, suggestion_id)
    if suggestion is None:
        raise DataSuggestionNotFound()
    build_key = f"workflows:data_suggestions:build:{team.id}:{suggestion_id}"
    built_before = cache.get(build_key)
    if isinstance(built_before, dict):
        return BuiltSuggestion(**built_before)

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
    with _analytics_client() as analytics_client:
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
            analytics_client=analytics_client,
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
    if built is None or not is_valid_draft(built.workflow):
        raise DataSuggestionBuildFailed()
    result = BuiltSuggestion(workflow=built.workflow, uses_saved_template=built.uses_saved_template)
    cache.set(build_key, dataclasses.asdict(result), _BUILD_CACHE_SECONDS)
    return result


def _unavailable_reason(team: Team) -> DataSuggestionsResult | None:
    if team.organization.is_ai_data_processing_approved is not True:
        return DataSuggestionsResult(status="ai_not_approved", suggestions=())
    # The Jev client cannot send the gateway's privacy header, so event names would be recorded. Until it can,
    # organizations in privacy mode get no suggestions.
    if is_privacy_mode_enabled(team):
        return _UNAVAILABLE
    # Without Jev the ranking cannot tell a sign-up from routine usage, so no suggestions are made.
    if not system_one_configured():
        return _UNAVAILABLE
    return None


def _cache_key(team: Team) -> str:
    # A team's first workflow moves it from the new to the existing ranking, so the two get separate entries.
    audience = "new" if _is_new_to_workflows(team) else "existing"
    return f"workflows:data_suggestions:v4:{team.id}:{audience}"


def _is_new_to_workflows(team: Team) -> bool:
    return not HogFlow.objects.filter(team_id=team.id).exclude(status="archived").exists()


def _generation_lock_key(team: Team) -> str:
    return _generation_lock_key_for(team.id)


def _generation_lock_key_for(team_id: int) -> str:
    return f"workflows:data_suggestions:generating:{team_id}"


def _release_lock(team_id: int, lock_token: str) -> None:
    # Only the run that holds the lock releases it, so a run that outlived its lease cannot drop a newer run's lock.
    key = _generation_lock_key_for(team_id)
    if cache.get(key) == lock_token:
        cache.delete(key)


def _to_cache(result: DataSuggestionsResult) -> dict[str, Any]:
    # Plain data, not a pickled class, so moving or renaming the dataclasses never breaks a cached entry.
    return dataclasses.asdict(result)


def _read_cache(team: Team) -> DataSuggestionsResult | None:
    stored = cache.get(_cache_key(team))
    if not isinstance(stored, dict):
        return None
    try:
        return DataSuggestionsResult(
            status=stored["status"],
            suggestions=tuple(
                DataSuggestion(**{**item, "step_outline": tuple(item["step_outline"])})
                for item in stored["suggestions"]
            ),
        )
    except (KeyError, TypeError):
        # An entry from before a field change is treated as missing, so the next visit generates new cards.
        return None


def _cached_suggestion(team: Team, suggestion_id: str) -> DataSuggestion | None:
    cached = _read_cache(team)
    if cached is None:
        return None
    return next((item for item in cached.suggestions if item.id == suggestion_id), None)


@contextmanager
def _analytics_client() -> Iterator[Any]:
    # The traces hold project event names and model output, so they go to the deployment's own region rather than
    # the process-wide client, which reports to the US project. Only cloud reports, like ph_scoped_capture. The
    # client flushes on exit, because a Celery task cannot rely on a background flush.
    client = get_client(get_instance_region() or "US") if is_cloud() else None
    try:
        yield client
    finally:
        if client is not None:
            client.shutdown()


def _generate(*, team: Team, user: User, analytics_client: Any) -> DataSuggestionsResult:
    try:
        return _suggest(team=team, user=user, analytics_client=analytics_client)
    except _GENERATION_ERRORS:
        return _UNAVAILABLE


def _suggest(*, team: Team, user: User, analytics_client: Any) -> DataSuggestionsResult:
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
        analytics_client=analytics_client,
    )
    if not ideas:
        return _UNAVAILABLE

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
