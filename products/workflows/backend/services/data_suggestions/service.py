import json
import uuid
import hashlib
import threading
import dataclasses
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

import structlog
import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.errors import CH_TRANSIENT_ERRORS, InternalCHQueryError
from posthog.event_usage import EventSource
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.exceptions_capture import capture_exception
from posthog.llm.system_one_client import system_one_configured
from posthog.models import Team, User
from posthog.models.organization import OrganizationMembership
from posthog.ph_client import get_client, ph_scoped_capture
from posthog.utils import get_instance_region

from products.messaging.backend.facade.api import EmailTemplateContent, EmailTemplateSummary, get_template_email_content
from products.workflows.backend.facade.contracts import (
    BuiltSuggestion,
    DataSuggestion,
    DataSuggestionNotFound,
    DataSuggestionsResult,
    EventWorkflowsBuild,
    MissingInput,
    PreparedIdeas,
)
from products.workflows.backend.models import WorkflowIdea as WorkflowIdeaRow
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.data_suggestions import team_context
from products.workflows.backend.services.data_suggestions.builder import (
    BuildContext,
    build_workflow,
    clean_copy,
    missing_inputs,
)
from products.workflows.backend.services.data_suggestions.event_volume import mobile_share, weekly_counts
from products.workflows.backend.services.data_suggestions.planner import (
    MAX_PLANNED_STEPS,
    Channel,
    IdeaContext,
    PlannedWorkflow,
    StepsContext,
    WorkflowIdea,
    plan_steps,
    suggest_ideas,
)
from products.workflows.backend.services.data_suggestions.premade import (
    is_premade_idea,
    lock_premade_idea,
    mark_accepted,
    premade_card,
    premade_suggestions,
    store_premade_ideas,
    waiting_premade_idea,
    with_push_channels,
    with_sender,
)
from products.workflows.backend.services.data_suggestions.ranking import (
    STAGE_WEIGHTS,
    pick_one_per_stage,
    select_prompt_events,
)
from products.workflows.backend.services.data_suggestions.stages import (
    MAX_CLASSIFIED_EVENTS,
    StageClassificationFailed,
    classify_event_stages,
)
from products.workflows.backend.services.hog_flow_templates import get_function_template_schema, list_step_templates

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
_PLAN_ATTEMPTS = 2
MAX_SUGGESTIONS = 3
# Each picked event costs one plan from the stronger model, so a request can name only a few.
MAX_PICKED_EVENTS = 5
_PROMPT_EVENTS_LIMIT = 60
_GENERATION_ERRORS = (
    StageClassificationFailed,
    InternalCHQueryError,
    ClickHouseQueryTimeOut,
    ClickHouseQueryMemoryLimitExceeded,
    *CH_TRANSIENT_ERRORS,
)

_GENERATING = DataSuggestionsResult(status="generating", suggestions=())
_BUILDING = BuiltSuggestion(status="building")
_BUILD_FAILED = BuiltSuggestion(status="failed")
_UNAVAILABLE = DataSuggestionsResult(status="unavailable", suggestions=())
_EVENTS_BUILDING = EventWorkflowsBuild(status="building")
_EVENTS_FAILED = EventWorkflowsBuild(status="failed")
# pinned: feature flag key - the destination modal, the build_for_events endpoint and the MCP tool all read it
DESTINATION_SUGGESTION_FLAG_KEY = "workflows-destination-suggestion"
_ONCE_PER_PERSON_STAGES = frozenset({"signup", "onboarding"})
_MOBILE_FIRST_SHARE = 0.5
# A project without a verified sender cannot pick one yet, so the field says what to do first.
NO_SENDER_FIELD = "Email sender (no verified sender yet: add a sending domain under Workflows > Channels)"


def get_data_suggestions(*, team: Team) -> DataSuggestionsResult:
    """The cards as they are now. This never runs a query or a model, so a read-only caller cannot cause spend."""
    # Checked before the premade cards too, because the models wrote them from the project's events.
    unavailable = _unavailable_reason(team)
    if unavailable is not None:
        return unavailable
    premade = _premade_result(team)
    if premade is not None:
        return premade
    # Checked before the cache, so a refresh in progress reads as generating rather than as the old cards.
    if cache.get(_generation_lock_key(team)) is not None:
        return _GENERATING
    return _read_cache(team) or _UNAVAILABLE


def data_suggestions_acting_user(team: Team) -> User | None:
    """The organization's longest-standing owner or admin, who runs the models when ideas are prepared ahead of time."""
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            level__gte=OrganizationMembership.Level.ADMIN,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("-level", "joined_at")
        .first()
    )
    return membership.user if membership is not None else None


def count_waiting_data_suggestions(*, team: Team) -> int:
    """The ideas this person would see on the empty workflows page. Like `get_data_suggestions`, it never runs a model."""
    if HogFlow.objects.filter(team_id=team.id).exclude(status=HogFlow.State.ARCHIVED).exists():
        return 0
    result = get_data_suggestions(team=team)
    return len(result.suggestions) if result.status == "ready" else 0


def start_data_suggestions(*, team: Team, refresh: bool, enqueue: Callable[[str], None]) -> DataSuggestionsResult:
    """Returns the cached cards, or starts a background run through `enqueue` and reports that it is generating.
    A project with premade ideas gets only those, and no run starts."""
    unavailable = _unavailable_reason(team)
    if unavailable is not None:
        return unavailable
    premade = _premade_result(team)
    if premade is not None:
        return premade
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


def email_sender_ready(*, team: Team) -> bool:
    return team_context.has_verified_email_sender(team)


def needs_new_generation(*, team: Team, refresh: bool) -> bool:
    """Whether a generate call would start a run, the only case that costs model time."""
    if _premade_result(team) is not None:
        return False
    # A refresh always counts, because the run it joins can end before the request reaches the lock.
    return refresh or (_read_cache(team) is None and cache.get(_generation_lock_key(team)) is None)


def run_data_suggestions(*, team_id: int, user_id: int, lock_token: str) -> None:
    """The background run that `start_data_suggestions` queues. It caches the result and releases the lock."""
    lock_key = _generation_lock_key_for(team_id)
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
        # A newer run owns the cache once this run lost the lock, and its suggestion ids must stay.
        if _lost_lock(lock_key, lock_token):
            return
        # Written before the lock is released, so the next visit reads it instead of starting another run.
        cache.set(_cache_key(team), _to_cache(result), ttl)
    finally:
        _release_lock(team_id, lock_token)


def start_build(
    *, team: Team, suggestion_id: str, caller: str, retry: bool, enqueue: Callable[[str], None]
) -> BuiltSuggestion:
    """The built draft, or a background build through `enqueue`. Ask again while the status is building.

    Each `caller` checks drafts the way its own create request does, so builds are stored per caller.

    A failed result stays until `retry` asks for a new build, so every tab that polls the build reads the failure.
    """
    if team.organization.is_ai_data_processing_approved is not True or _cached_suggestion(team, suggestion_id) is None:
        raise DataSuggestionNotFound()
    stored = _current_build(team, suggestion_id, caller)
    if stored is not None and not (retry and stored.status == "failed"):
        return stored
    # A second click or tab while a build runs would pay for another plan.
    lock_token = str(uuid.uuid4())
    if not cache.add(_build_lock_key(team.id, suggestion_id, caller), lock_token, _GENERATION_LOCK_SECONDS):
        return _BUILDING
    # Cleared once the lock is held, so the polls of this retry read building instead of the old failure.
    cache.delete(_build_key(team.id, suggestion_id, caller))
    try:
        enqueue(lock_token)
    except Exception:
        _release(_build_lock_key(team.id, suggestion_id, caller), lock_token)
        logger.exception("workflows.data_suggestions.build_enqueue_failed", team_id=team.id)
        return _BUILD_FAILED
    # A worker that ran inline, like in tests, has already stored the result.
    return _read_build(team.id, suggestion_id, caller) or _BUILDING


def save_premade_draft(
    *,
    team: Team,
    user: User,
    idea_id: str,
    caller: str,
    validate_draft: Callable[[Team, dict[str, Any]], dict[str, Any] | None],
    save_draft: Callable[[Team, User, dict[str, Any]], str],
) -> BuiltSuggestion | None:
    """Saves a premade idea's workflow as a draft and marks the idea accepted, or returns None when the id is not a
    premade idea. The idea row stays locked until both writes commit, so a second call cannot save a second draft."""
    if _unavailable_reason(team) is not None:
        raise DataSuggestionNotFound()
    with transaction.atomic():
        row = lock_premade_idea(team.id, idea_id)
        if row is None:
            return None
        workflow = _premade_workflow(team, row)
        validated = validate_draft(team, workflow)
        if validated is None:
            return _BUILD_FAILED
        workflow_id = save_draft(team, user, validated)
        mark_accepted(row, team_id=team.id, hog_flow_id=workflow_id, user=user)
    result = dataclasses.replace(_premade_build(team, row, workflow), workflow_id=workflow_id)
    # The web page sends this event itself, with the surface the card was on.
    if not caller.startswith(f"{EventSource.WEB.value}:"):
        # The process-wide client sends in the background, so the request does not wait for a flush.
        _capture_saved_build(
            capture=posthoganalytics.capture, user=user, suggestion=premade_card(row), result=result, caller=caller
        )
    return result


def get_premade_workflow(
    *, team: Team, idea_id: str, validate_draft: Callable[[Team, dict[str, Any]], dict[str, Any] | None]
) -> BuiltSuggestion | None:
    """A waiting premade idea's workflow without saving it, or None when the id is not a waiting premade idea. The
    idea stays offered until a call saves it."""
    if _unavailable_reason(team) is not None:
        raise DataSuggestionNotFound()
    row = waiting_premade_idea(team.id, idea_id)
    if row is None:
        return None
    workflow = _premade_workflow(team, row)
    if validate_draft(team, workflow) is None:
        return _BUILD_FAILED
    return _premade_build(team, row, workflow)


def _premade_workflow(team: Team, row: WorkflowIdeaRow) -> dict[str, Any]:
    workflow = with_sender(row.definition, team_context.email_sender(team))
    return with_push_channels(workflow, team_context.push_integration_ids(team))


def _premade_build(team: Team, row: WorkflowIdeaRow, workflow: dict[str, Any]) -> BuiltSuggestion:
    return BuiltSuggestion(
        status="ready",
        workflow=workflow,
        uses_saved_template=bool(row.evidence.get("uses_saved_template")),
        missing_inputs=_missing_inputs(team, workflow),
    )


def build_caller(event_source: str, *, save: bool, user_id: int) -> str:
    """The key a build is stored under. A saved build is checked with the editor's draft rules, so it differs from an
    unsaved build for the same caller. A saved build is also kept per user, because its draft can carry access
    restrictions another editor of the project does not pass."""
    return f"{event_source}:save:{user_id}" if save else event_source


def needs_new_build(*, team: Team, suggestion_id: str, caller: str, retry: bool) -> bool:
    """Whether a build call would start planning, the only case that costs model time."""
    if is_premade_idea(team.id, suggestion_id):
        return False
    stored = _current_build(team, suggestion_id, caller)
    reusable = stored is not None and not (retry and stored.status == "failed")
    return not reusable and cache.get(_build_lock_key(team.id, suggestion_id, caller)) is None


def run_build(
    *,
    team_id: int,
    user_id: int,
    suggestion_id: str,
    caller: str,
    lock_token: str,
    validate_draft: Callable[[Team, dict[str, Any]], dict[str, Any] | None],
    save_draft: Callable[[Team, User, dict[str, Any]], str] | None = None,
) -> None:
    """The background build that `start_build` queues. It stores the result and releases the lock. With `save_draft`
    it also saves the draft, for callers like agents that cannot save one in the editor."""
    lock_key = _build_lock_key(team_id, suggestion_id, caller)
    try:
        try:
            team = Team.objects.select_related("organization").get(id=team_id)
            user = User.objects.get(id=user_id)
            cached = _read_cache(team)
            suggestion = _cached_suggestion(team, suggestion_id)
            # Consent can change between the click and the worker picking the build up.
            if team.organization.is_ai_data_processing_approved is not True or suggestion is None or cached is None:
                result = _BUILD_FAILED
            else:
                result, validated = _plan_and_build(
                    team=team,
                    user=user,
                    suggestion=suggestion,
                    events=cached.events,
                    mobile_first=cached.mobile_first,
                    validate_draft=validate_draft,
                )
                # A task that outlived its lock would save a second draft next to the newer run's draft.
                if save_draft is not None and validated is not None and not _lost_lock(lock_key, lock_token):
                    result = dataclasses.replace(result, workflow_id=save_draft(team, user, validated))
        except Exception as error:
            # Without a stored failure the next poll finds no result and no lock, and queues the same build again.
            logger.exception("workflows.data_suggestions.build_failed", team_id=team_id)
            capture_exception(error, {"team_id": team_id})
            result = _BUILD_FAILED
        ttl = _BUILD_CACHE_SECONDS if result.status == "ready" else FAILURE_CACHE_TTL_SECONDS
        if not _lost_lock(lock_key, lock_token):
            cache.set(_build_key(team_id, suggestion_id, caller), dataclasses.asdict(result), ttl)
        # Sent after the result is stored, so a slow analytics delivery never keeps a saved draft reading as building.
        if result.workflow_id is not None and suggestion is not None:
            with ph_scoped_capture() as capture:
                _capture_saved_build(capture=capture, user=user, suggestion=suggestion, result=result, caller=caller)
    finally:
        _release(lock_key, lock_token)


def event_workflows_available(*, team: Team) -> bool:
    """Whether workflows can be built for picked events. Unlike the cards, this needs no Jev, because the team named
    the events itself."""
    return team.organization.is_ai_data_processing_approved is True and not is_privacy_mode_enabled(team)


def start_event_workflows(
    *, team: Team, user_id: int, events: tuple[str, ...], retry: bool, enqueue: Callable[[str], None]
) -> EventWorkflowsBuild:
    """The drafts built for these events, or a background build through `enqueue`. Ask again with the same events
    while the status is building. A failed result stays until `retry` asks for a new build."""
    key = _event_build_key(team.id, user_id, events)
    stored = _read_event_build(key)
    if stored is not None and not (retry and stored.status == "failed"):
        return stored
    lock_key = _event_build_lock_key(team.id, user_id, events)
    lock_token = str(uuid.uuid4())
    # A second click or tab while a build runs would pay for the same plans again.
    if not cache.add(lock_key, lock_token, _GENERATION_LOCK_SECONDS):
        return _EVENTS_BUILDING
    cache.delete(key)
    try:
        enqueue(lock_token)
    except Exception:
        _release(lock_key, lock_token)
        logger.exception("workflows.data_suggestions.event_build_enqueue_failed", team_id=team.id)
        return _EVENTS_FAILED
    # A worker that ran inline, like in tests, has already stored the result.
    return _read_event_build(key) or _EVENTS_BUILDING


def needs_new_event_workflows(*, team: Team, user_id: int, events: tuple[str, ...], retry: bool) -> bool:
    """Whether a call would start planning, the only case that costs model time."""
    stored = _read_event_build(_event_build_key(team.id, user_id, events))
    reusable = stored is not None and not (retry and stored.status == "failed")
    return not reusable and cache.get(_event_build_lock_key(team.id, user_id, events)) is None


def run_event_workflows(
    *,
    team_id: int,
    user_id: int,
    events: tuple[str, ...],
    lock_token: str,
    validate_draft: Callable[[Team, dict[str, Any]], dict[str, Any] | None],
    save_draft: Callable[[Team, User, dict[str, Any]], str],
) -> None:
    """The background build that `start_event_workflows` queues. It saves one draft per event that plans cleanly,
    stores the ids and releases the lock."""
    lock_key = _event_build_lock_key(team_id, user_id, events)
    try:
        try:
            team = Team.objects.select_related("organization").get(id=team_id)
            user = User.objects.get(id=user_id)
            # Consent can change between the click and the worker picking the build up.
            if not event_workflows_available(team=team):
                result = _EVENTS_FAILED
            else:
                result = _build_event_workflows(
                    team=team,
                    user=user,
                    events=events,
                    validate_draft=validate_draft,
                    save_draft=save_draft,
                    still_owns_lock=lambda: not _lost_lock(lock_key, lock_token),
                )
        except Exception as error:
            # Without a stored failure the next poll finds no result and no lock, and queues the same build again.
            logger.exception("workflows.data_suggestions.event_build_failed", team_id=team_id)
            capture_exception(error, {"team_id": team_id})
            result = _EVENTS_FAILED
        ttl = _BUILD_CACHE_SECONDS if result.status == "ready" else FAILURE_CACHE_TTL_SECONDS
        if not _lost_lock(lock_key, lock_token):
            cache.set(_event_build_key(team_id, user_id, events), dataclasses.asdict(result), ttl)
    finally:
        _release(lock_key, lock_token)


def _build_event_workflows(
    *,
    team: Team,
    user: User,
    events: tuple[str, ...],
    validate_draft: Callable[[Team, dict[str, Any]], dict[str, Any] | None],
    save_draft: Callable[[Team, User, dict[str, Any]], str],
    still_owns_lock: Callable[[], bool],
) -> EventWorkflowsBuild:
    all_counts = weekly_counts(team)
    # A step can wait on any busy event, not only the picked ones.
    planning_events = tuple(name for name, _ in select_prompt_events(all_counts, limit=_PROMPT_EVENTS_LIMIT))
    # A batch that waited in the queue past its lock is replaced by a newer one, so it stops before any model call.
    if not still_owns_lock():
        return _EVENTS_FAILED
    with _analytics_client() as analytics_client:
        ideas = suggest_ideas(
            team=team,
            user=user,
            context=IdeaContext(
                events=tuple((event, all_counts.get(event, 0)) for event in events),
                stages={},
                channels=team_context.channels(team),
                has_slack=team_context.slack_integration_id(team) is not None,
                picked_events=True,
            ),
            analytics_client=analytics_client,
        )
    workflow_ids: list[str] = []
    seen_events: set[str] = set()
    for idea in ideas:
        outline = tuple(idea.step_outline[:MAX_PLANNED_STEPS])
        # The model can only pick from the listed events; anything else is a made-up name.
        if idea.trigger_event not in events or idea.trigger_event in seen_events or not outline:
            continue
        # Each plan is a call to the stronger model, so a batch that lost its lock does not pay for the rest.
        if not still_owns_lock():
            break
        seen_events.add(idea.trigger_event)
        suggestion = DataSuggestion(
            id=str(uuid.uuid4()),
            name=clean_copy(idea.name)[:50],
            description=clean_copy(idea.description),
            reason=clean_copy(idea.reason),
            trigger_event=idea.trigger_event,
            weekly_count=all_counts.get(idea.trigger_event, 0),
            stage="other",
            step_outline=outline,
        )
        try:
            _, validated = _plan_and_build(
                team=team,
                user=user,
                suggestion=suggestion,
                events=planning_events,
                # Picked events get an email workflow each, so push stays out whatever the project's app is.
                mobile_first=False,
                validate_draft=validate_draft,
                picked_events=True,
            )
            # A task that outlived its lock would save drafts next to the newer run's drafts.
            if validated is None or not still_owns_lock():
                continue
            workflow_ids.append(save_draft(team, user, validated))
        except Exception as error:
            # The drafts saved for earlier events stay in the result, so a retry does not save them a second time.
            logger.exception("workflows.data_suggestions.event_build_item_failed", team_id=team.id)
            capture_exception(error, {"team_id": team.id})
    return EventWorkflowsBuild(status="ready" if workflow_ids else "failed", workflow_ids=tuple(workflow_ids))


def prepare_premade_ideas(
    *,
    team: Team,
    user: User,
    validate_draft: Callable[[Team, dict[str, Any]], dict[str, Any] | None],
) -> PreparedIdeas:
    """Generates the cards and builds each one now, then stores them as premade ideas. Nothing is cached, so the
    project's own generation runs are not affected."""
    unavailable = _unavailable_reason(team)
    if unavailable is not None:
        return PreparedIdeas(status=unavailable.status)
    with _analytics_client() as analytics_client:
        result = _generate(team=team, user=user, analytics_client=analytics_client)
    if result.status != "ready":
        return PreparedIdeas(status=result.status)
    built: list[tuple[DataSuggestion, BuiltSuggestion]] = []
    for suggestion in result.suggestions:
        try:
            build, _ = _plan_and_build(
                team=team,
                user=user,
                suggestion=suggestion,
                events=result.events,
                mobile_first=result.mobile_first,
                validate_draft=validate_draft,
            )
        except Exception as error:
            logger.exception("workflows.data_suggestions.prepare_build_failed", team_id=team.id)
            capture_exception(error, {"team_id": team.id})
            build = _BUILD_FAILED
        if build.status == "ready":
            built.append((suggestion, build))
    stored = store_premade_ideas(team=team, built=built)
    return PreparedIdeas(status="ready", stored=stored, failed_builds=len(result.suggestions) - len(built))


def _plan_and_build(
    *,
    team: Team,
    user: User,
    suggestion: DataSuggestion,
    events: tuple[str, ...],
    mobile_first: bool,
    validate_draft: Callable[[Team, dict[str, Any]], dict[str, Any] | None],
    picked_events: bool = False,
) -> tuple[BuiltSuggestion, dict[str, Any] | None]:
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
    channels = _offered_channels(team, mobile_first)
    event_properties = team_context.event_property_names(team, suggestion.trigger_event)
    try:
        person_properties = team_context.person_properties(team)
    except _GENERATION_ERRORS:
        # Without them a branch keeps an empty condition for the team to set, which is no reason to fail the build.
        person_properties = {}
    context = BuildContext(
        allowed_events=frozenset({suggestion.trigger_event, *events}),
        step_template_ids=frozenset(template.template_id for template in step_templates),
        channels=channels,
        email_templates={},
        sender=team_context.email_sender(team),
        slack_integration_id=slack_integration_id,
        once_per_person=suggestion.stage in _ONCE_PER_PERSON_STAGES,
        event_properties=frozenset(event_properties),
        weekly_count=suggestion.weekly_count,
        person_properties=person_properties,
        push_integration_ids=team_context.push_integration_ids(team),
    )
    built = None
    # The model now and then links a step to an id it never wrote. A second plan almost always holds up.
    for _ in range(_PLAN_ATTEMPTS):
        with _analytics_client() as analytics_client:
            plan = plan_steps(
                team=team,
                user=user,
                context=StepsContext(
                    idea=idea,
                    email_templates=email_templates,
                    step_templates=step_templates,
                    events=events,
                    channels=channels,
                    has_slack=slack_integration_id is not None,
                    picked_events=picked_events,
                    event_properties=event_properties,
                    person_properties=person_properties,
                    mobile_first=mobile_first,
                ),
                analytics_client=analytics_client,
            )
        if plan is None:
            return _BUILD_FAILED, None
        built = build_workflow(
            idea,
            plan,
            dataclasses.replace(context, email_templates=_chosen_template_bodies(team, plan, email_templates)),
        )
        if built is not None:
            break
    if built is None:
        return _BUILD_FAILED, None
    validated = validate_draft(team, built.workflow)
    # Saved templates are copied into every email step, and a draft larger than a request body cannot be saved.
    if validated is None or len(json.dumps(built.workflow)) > settings.DATA_UPLOAD_MAX_MEMORY_SIZE:
        return _BUILD_FAILED, None
    result = BuiltSuggestion(
        status="ready",
        workflow=built.workflow,
        uses_saved_template=built.uses_saved_template,
        missing_inputs=_missing_inputs(team, built.workflow),
    )
    return result, validated


def _premade_result(team: Team) -> DataSuggestionsResult | None:
    cards = premade_suggestions(team)
    return DataSuggestionsResult(status="ready", suggestions=cards) if cards else None


def _current_build(team: Team, suggestion_id: str, caller: str) -> BuiltSuggestion | None:
    """The stored build. A saved draft is read again, so a deleted draft gets a new build and the blank settings
    match the draft as it is now, for example after the team added a sender."""
    stored = _read_build(team.id, suggestion_id, caller)
    if stored is None or stored.workflow_id is None:
        return stored
    actions = team_context.saved_workflow_actions(team, stored.workflow_id)
    if actions is None:
        return None
    return dataclasses.replace(stored, missing_inputs=_missing_inputs(team, {"actions": actions}))


def _offered_channels(team: Team, mobile_first: bool) -> frozenset[Channel]:
    """The channels a plan may use. A mobile-first project gets push even before it connects a provider, and the
    step's note asks the team to connect one."""
    connected = team_context.channels(team)
    push: frozenset[Channel] = frozenset({"push"})
    return connected | push if mobile_first else connected


def _missing_inputs(team: Team, workflow: dict[str, Any]) -> tuple[MissingInput, ...]:
    return missing_inputs(
        workflow,
        _input_schemas(workflow),
        sender_field="Email sender" if team_context.has_verified_email_sender(team) else NO_SENDER_FIELD,
    )


def _input_schemas(workflow: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    template_ids = {(action.get("config") or {}).get("template_id") for action in workflow["actions"]}
    schemas: dict[str, list[dict[str, Any]]] = {}
    for template_id in {template_id for template_id in template_ids if isinstance(template_id, str)}:
        schema = get_function_template_schema(template_id)
        if schema is not None:
            schemas[template_id] = list(schema.inputs_schema or [])
    return schemas


def _capture_saved_build(
    *, capture: Callable[..., object], user: User, suggestion: DataSuggestion, result: BuiltSuggestion, caller: str
) -> None:
    # The web page sends this event from the browser. A saved build has no browser, so the funnel gets it from here.
    # pinned: analytics event name - renaming breaks dashboards
    capture(
        distinct_id=user.distinct_id,
        event="workflows data suggestion built",
        properties={
            "workflow_id": result.workflow_id,
            "source": caller.split(":")[0],
            "trigger_event": suggestion.trigger_event,
            "stage": suggestion.stage,
            "uses_saved_template": result.uses_saved_template,
            "missing_inputs": len(result.missing_inputs),
        },
    )


def _chosen_template_bodies(
    team: Team, plan: PlannedWorkflow, summaries: tuple[EmailTemplateSummary, ...]
) -> dict[str, EmailTemplateContent]:
    # Saved designs can be large, so only the bodies of the templates the plan picked are loaded.
    chosen = {step.email_template_id for step in plan.steps if step.email_template_id}
    bodies: dict[str, EmailTemplateContent] = {}
    for summary in summaries:
        if str(summary.id) not in chosen:
            continue
        email = get_template_email_content(team.id, summary.id)
        if email is not None:
            bodies[str(summary.id)] = EmailTemplateContent(id=summary.id, name=summary.name, email=email)
    return bodies


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
    return f"workflows:data_suggestions:v4:{team.id}"


def _generation_lock_key(team: Team) -> str:
    return _generation_lock_key_for(team.id)


def _generation_lock_key_for(team_id: int) -> str:
    return f"workflows:data_suggestions:generating:{team_id}"


def _release_lock(team_id: int, lock_token: str) -> None:
    _release(_generation_lock_key_for(team_id), lock_token)


def _lost_lock(key: str, lock_token: str) -> bool:
    # Reads can come from a Redis replica, which may not have the lock yet. Only another run's token means a newer run
    # took over, so a missing lock does not count.
    holder = cache.get(key)
    return holder is not None and holder != lock_token


def _release(key: str, lock_token: str) -> None:
    # Only the run that holds the lock releases it, so a run that outlived its lease cannot drop a newer run's lock.
    if cache.get(key) == lock_token:
        cache.delete(key)


def _build_key(team_id: int, suggestion_id: str, caller: str) -> str:
    return f"workflows:data_suggestions:build:{team_id}:{suggestion_id}:{caller}"


def _build_lock_key(team_id: int, suggestion_id: str, caller: str) -> str:
    return f"workflows:data_suggestions:building:{team_id}:{suggestion_id}:{caller}"


def _events_digest(events: tuple[str, ...]) -> str:
    # Event names can hold any character and be long, so the cache key carries a digest of the sorted names.
    return hashlib.sha256(json.dumps(sorted(set(events))).encode()).hexdigest()[:32]


def _event_build_key(team_id: int, user_id: int, events: tuple[str, ...]) -> str:
    return f"workflows:data_suggestions:event_build:{team_id}:{user_id}:{_events_digest(events)}"


def _event_build_lock_key(team_id: int, user_id: int, events: tuple[str, ...]) -> str:
    return f"workflows:data_suggestions:event_building:{team_id}:{user_id}:{_events_digest(events)}"


def _read_event_build(key: str) -> EventWorkflowsBuild | None:
    stored = cache.get(key)
    if not isinstance(stored, dict):
        return None
    try:
        return EventWorkflowsBuild(status=stored["status"], workflow_ids=tuple(stored["workflow_ids"]))
    except (KeyError, TypeError):
        return None


def _read_build(team_id: int, suggestion_id: str, caller: str) -> BuiltSuggestion | None:
    stored = cache.get(_build_key(team_id, suggestion_id, caller))
    if not isinstance(stored, dict):
        return None
    try:
        return BuiltSuggestion(
            **{**stored, "missing_inputs": tuple(MissingInput(**item) for item in stored.get("missing_inputs") or ())}
        )
    except TypeError:
        return None


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
            events=tuple(stored["events"]),
            # Cards cached before the share was stored were made without push, so their builds stay without it.
            mobile_first=bool(stored.get("mobile_first", False)),
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
    # client flushes on exit, because a Celery task cannot rely on a background flush. The flush runs in its own
    # thread, so an ingestion outage cannot hold back the result or the worker.
    client = get_client(get_instance_region() or "US") if is_cloud() else None
    try:
        yield client
    finally:
        if client is not None:
            threading.Thread(target=client.shutdown, daemon=True).start()


def _generate(*, team: Team, user: User, analytics_client: Any) -> DataSuggestionsResult:
    try:
        return _suggest(team=team, user=user, analytics_client=analytics_client)
    except _GENERATION_ERRORS:
        return _UNAVAILABLE
    except Exception as error:
        # Any other failure, like a database error, is cached as unavailable too, so the next visit does not repeat
        # the counts and the classification straight away.
        logger.exception("workflows.data_suggestions.generation_failed", team_id=team.id)
        capture_exception(error, {"team_id": team.id})
        return _UNAVAILABLE


def _suggest(*, team: Team, user: User, analytics_client: Any) -> DataSuggestionsResult:
    used_events = team_context.used_trigger_events(team)
    # The model can copy an event name into its JSON answer without escaping its quotes, which breaks the answer and
    # loses every idea of the run. Names that JSON must escape are left out.
    all_counts = {name: count for name, count in weekly_counts(team).items() if '"' not in name and "\\" not in name}
    # A build can wait on any busy event, including one another workflow already starts from.
    planning_events = tuple(name for name, _ in select_prompt_events(all_counts, limit=_PROMPT_EVENTS_LIMIT))
    counts = {name: count for name, count in all_counts.items() if name not in used_events}
    if not counts:
        return DataSuggestionsResult(status="ready", suggestions=())

    candidates = select_prompt_events(counts, limit=MAX_CLASSIFIED_EVENTS)
    jev_stages = classify_event_stages(team_id=team.id, event_names=[name for name, _ in candidates])
    prompt_events = select_prompt_events(counts, limit=_PROMPT_EVENTS_LIMIT, stages=jev_stages)
    if not prompt_events:
        return DataSuggestionsResult(status="ready", suggestions=())
    offered = {name for name, _ in prompt_events}
    mobile_first = mobile_share(team) >= _MOBILE_FIRST_SHARE
    channels = _offered_channels(team, mobile_first)
    ideas = suggest_ideas(
        team=team,
        user=user,
        context=IdeaContext(
            events=tuple(prompt_events),
            stages=jev_stages,
            channels=channels,
            has_slack=team_context.slack_integration_id(team) is not None,
            mobile_first=mobile_first,
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
    # The sort is stable, so within a stage the model's order wins. A busier event is not a better moment: a
    # dismissed upgrade dialog fires more often than a started checkout.
    ranked = sorted(suggestions, key=lambda item: STAGE_WEIGHTS[item.stage], reverse=True)
    return DataSuggestionsResult(
        status="ready",
        suggestions=tuple(pick_one_per_stage(ranked, stage_of=lambda item: item.stage, limit=MAX_SUGGESTIONS)),
        events=planning_events,
        mobile_first=mobile_first,
    )
