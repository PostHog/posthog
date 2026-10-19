import uuid
import threading
import dataclasses
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from django.core.cache import cache

import structlog
import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.errors import CH_TRANSIENT_ERRORS, InternalCHQueryError
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models import Team, User
from posthog.ph_client import get_client
from posthog.utils import get_instance_region

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.workflows.backend.facade.contracts import (
    AudienceSuggestion,
    AudienceSuggestionsResult,
    DataSuggestionNotFound,
)
from products.workflows.backend.services.audience_suggestions.audience import (
    EMAIL_PROPERTY,
    activity_counts,
    cohort_filters,
    reachable_count,
)
from products.workflows.backend.services.audience_suggestions.planner import AudienceIdea, suggest_audiences
from products.workflows.backend.services.data_suggestions.builder import clean_copy
from products.workflows.backend.services.data_suggestions.event_volume import weekly_counts
from products.workflows.backend.services.data_suggestions.ranking import MIN_WEEKLY_COUNT, guess_stage

from ee.hogai.utils.feature_flags import is_privacy_mode_enabled

logger = structlog.get_logger(__name__)

# pinned: feature flag key - the frontend gates the same surface on it
FEATURE_FLAG_KEY = "workflows-broadcast-audience-suggestions"
CACHE_TTL_SECONDS = 24 * 60 * 60
FAILURE_CACHE_TTL_SECONDS = 5 * 60
_GENERATION_LOCK_SECONDS = 15 * 60
MAX_SUGGESTIONS = 3
# A smaller audience is better written to one by one than broadcast to.
MIN_REACHABLE = 10
# Broadcast audiences often come from feature use, which busy telemetry events push down a volume ranking, so the
# model sees far more events than the workflow ideas do. Names are short, so the prompt stays small.
_PROMPT_EVENTS_LIMIT = 300
_LIFECYCLE_EVENTS_LIMIT = 60
_COUNT_ERRORS = (InternalCHQueryError, ClickHouseQueryTimeOut, ClickHouseQueryMemoryLimitExceeded, *CH_TRANSIENT_ERRORS)

_GENERATING = AudienceSuggestionsResult(status="generating", suggestions=())
_UNAVAILABLE = AudienceSuggestionsResult(status="unavailable", suggestions=())


def is_enabled(user: User, organization_id: str) -> bool:
    return bool(
        user.distinct_id
        and posthoganalytics.feature_enabled(
            FEATURE_FLAG_KEY,
            user.distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
        )
    )


def can_read_email(user: User, team_id: int) -> bool:
    """The cards count people by their email address, so only someone who can read it may see them."""
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
    return EMAIL_PROPERTY not in split_restricted_property_names(restrictions).person


def get_audience_suggestions(*, team: Team) -> AudienceSuggestionsResult:
    """The cards as they are now. This never runs a query or a model."""
    unavailable = _unavailable_reason(team)
    if unavailable is not None:
        return unavailable
    if cache.get(_lock_key(team.id)) is not None:
        return _GENERATING
    return _read_cache(team.id) or _UNAVAILABLE


def needs_new_generation(*, team: Team, refresh: bool) -> bool:
    return refresh or (_read_cache(team.id) is None and cache.get(_lock_key(team.id)) is None)


def start_audience_suggestions(
    *, team: Team, refresh: bool, enqueue: Callable[[str], None]
) -> AudienceSuggestionsResult:
    unavailable = _unavailable_reason(team)
    if unavailable is not None:
        return unavailable
    cached = _read_cache(team.id)
    if cached is not None and not refresh:
        return cached
    lock_token = str(uuid.uuid4())
    if not cache.add(_lock_key(team.id), lock_token, _GENERATION_LOCK_SECONDS):
        return _GENERATING
    try:
        enqueue(lock_token)
    except Exception:
        _release(team.id, lock_token)
        logger.exception("workflows.audience_suggestions.enqueue_failed", team_id=team.id)
        return _UNAVAILABLE
    return _GENERATING


def run_audience_suggestions(*, team_id: int, user_id: int, lock_token: str) -> None:
    try:
        # A task the queue held past the lock's lifetime lost its run to a newer one, so it does no work.
        if cache.get(_lock_key(team_id)) != lock_token:
            return
        team = Team.objects.select_related("organization").get(id=team_id)
        user = User.objects.get(id=user_id)
        if _unavailable_reason(team) is not None:
            return
        previous = _read_cache(team_id)
        try:
            with _analytics_client() as analytics_client:
                result = _suggest(team=team, user=user, analytics_client=analytics_client)
        except _COUNT_ERRORS:
            logger.warning("workflows.audience_suggestions.query_failed", team_id=team_id, exc_info=True)
            result = _UNAVAILABLE
        # A failed refresh keeps the working cards, so a click on one still finds it.
        if result.status != "ready" and previous is not None and previous.status == "ready":
            return
        ttl = CACHE_TTL_SECONDS if result.status == "ready" and result.suggestions else FAILURE_CACHE_TTL_SECONDS
        if cache.get(_lock_key(team_id)) != lock_token:
            return
        cache.set(_cache_key(team_id), _to_cache(result), ttl)
    finally:
        _release(team_id, lock_token)


def get_audience_suggestion(*, team: Team, suggestion_id: str) -> AudienceSuggestion:
    cached = _read_cache(team.id)
    match = next((item for item in cached.suggestions if item.id == suggestion_id), None) if cached else None
    if match is None:
        raise DataSuggestionNotFound()
    return match


def _suggest(*, team: Team, user: User, analytics_client: Any) -> AudienceSuggestionsResult:
    counts = {**weekly_counts(team), **activity_counts(team, user)}
    events = prompt_events(counts)
    if not events:
        return AudienceSuggestionsResult(status="ready", suggestions=())
    ideas = suggest_audiences(team=team, user=user, events=events, analytics_client=analytics_client)
    if not ideas:
        return _UNAVAILABLE
    sized: list[AudienceSuggestion] = []
    failed = 0
    for idea in ideas:
        # One audience too costly to count drops that idea only, not the cards that counted fine.
        try:
            suggestion = _sized(team, user, idea, counts)
        except _COUNT_ERRORS:
            logger.warning(
                "workflows.audience_suggestions.count_failed", team_id=team.id, kind=idea.kind, exc_info=True
            )
            failed += 1
            continue
        if suggestion is not None:
            sized.append(suggestion)
    if failed and not sized:
        return _UNAVAILABLE
    return AudienceSuggestionsResult(status="ready", suggestions=_pick(sized))


def prompt_events(counts: dict[str, int]) -> tuple[tuple[str, int], ...]:
    """Lifecycle-looking events first, so a quiet sign-up is not cut, then the rest by volume. Failure events are left
    out: a broadcast to people who hit an error belongs to the error, not to a suggestion."""
    eligible = sorted(
        (
            (name, count)
            for name, count in counts.items()
            if count >= MIN_WEEKLY_COUNT and guess_stage(name) != "failure"
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    lifecycle = [item for item in eligible if guess_stage(item[0]) != "other"][:_LIFECYCLE_EVENTS_LIMIT]
    chosen = {name for name, _ in lifecycle}
    return tuple([*lifecycle, *(item for item in eligible if item[0] not in chosen)][:_PROMPT_EVENTS_LIMIT])


def _sized(team: Team, user: User, idea: AudienceIdea, counts: dict[str, int]) -> AudienceSuggestion | None:
    # The schema limits the names to the listed events. The checks below catch a plan that does not fit its kind.
    if idea.event not in counts:
        return None
    missing_event = idea.missing_event if idea.kind == "not_yet" else None
    if idea.kind == "not_yet" and (missing_event not in counts or missing_event == idea.event):
        return None
    min_count = (idea.min_count or 3) if idea.kind == "regulars" else None
    shape: dict[str, Any] = {
        "kind": idea.kind,
        "event": idea.event,
        "missing_event": missing_event,
        "window_days": idea.window_days,
        "min_count": min_count,
    }
    size = reachable_count(team, user=user, **shape)
    if size < MIN_REACHABLE:
        return None
    return AudienceSuggestion(
        id=str(uuid.uuid4()),
        name=clean_copy(idea.name)[:50],
        description=clean_copy(idea.description)[:300],
        reason=clean_copy(idea.reason)[:200],
        reachable_count=size,
        cohort_filters=cohort_filters(**shape),
        **shape,
    )


def _pick(suggestions: list[AudienceSuggestion]) -> tuple[AudienceSuggestion, ...]:
    # One card per kind first, in the model's order, so the cards show different reasons to send.
    picked: list[AudienceSuggestion] = []
    for suggestion in suggestions:
        if suggestion.kind not in {item.kind for item in picked}:
            picked.append(suggestion)
    for suggestion in suggestions:
        if len(picked) >= MAX_SUGGESTIONS:
            break
        if suggestion not in picked:
            picked.append(suggestion)
    return tuple(picked[:MAX_SUGGESTIONS])


def _unavailable_reason(team: Team) -> AudienceSuggestionsResult | None:
    if team.organization.is_ai_data_processing_approved is not True:
        return AudienceSuggestionsResult(status="ai_not_approved", suggestions=())
    if is_privacy_mode_enabled(team):
        return _UNAVAILABLE
    return None


@contextmanager
def _analytics_client() -> Iterator[Any]:
    # Traces go to the deployment's own region, and a Celery task cannot rely on a background flush.
    client = get_client(get_instance_region() or "US") if is_cloud() else None
    try:
        yield client
    finally:
        if client is not None:
            threading.Thread(target=client.shutdown, daemon=True).start()


def _cache_key(team_id: int) -> str:
    return f"workflows:audience_suggestions:v1:{team_id}"


def _lock_key(team_id: int) -> str:
    return f"workflows:audience_suggestions:lock:{team_id}"


def _release(team_id: int, lock_token: str) -> None:
    if cache.get(_lock_key(team_id)) == lock_token:
        cache.delete(_lock_key(team_id))


def _to_cache(result: AudienceSuggestionsResult) -> dict[str, Any]:
    return dataclasses.asdict(result)


def _read_cache(team_id: int) -> AudienceSuggestionsResult | None:
    raw = cache.get(_cache_key(team_id))
    if not isinstance(raw, dict):
        return None
    try:
        return AudienceSuggestionsResult(
            status=raw["status"], suggestions=tuple(AudienceSuggestion(**item) for item in raw["suggestions"])
        )
    except (KeyError, TypeError):
        return None
