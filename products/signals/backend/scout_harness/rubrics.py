from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

import structlog
from pydantic import BaseModel, Field

from posthog.dataclasses import frozen
from posthog.exceptions import Conflict
from posthog.temporal.common.client import sync_connect

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.rubrics_schema import (
    MAX_CRITERIA as MAX_CRITERIA,
    MAX_SUGGESTIONS as MAX_SUGGESTIONS,
    ScoutRubricCriterion as ScoutRubricCriterion,
    ScoutRubricSource as ScoutRubricSource,
    ScoutRubricSuggestion as ScoutRubricSuggestion,
    ScoutRubricSuggestionBatch as ScoutRubricSuggestionBatch,
    default_criteria as default_criteria,
)

logger = structlog.get_logger(__name__)

RUBRIC_TEAM_ID = 2
GENERATION_TIMEOUT = timedelta(minutes=30)


class ScoutRubricGenerationStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class ScoutRubricGeneration(BaseModel):
    id: str
    status: ScoutRubricGenerationStatus
    requested_at: datetime
    completed_at: datetime | None = None
    task_id: str | None = None
    task_run_id: str | None = None
    error: str | None = None
    suggestions: list[ScoutRubricCriterion] = Field(default_factory=list)
    summary: str = ""


class ScoutRubricState(BaseModel):
    revision: int = 0
    criteria: list[ScoutRubricCriterion] = Field(default_factory=list)
    generation: ScoutRubricGeneration | None = None


@frozen
class ScoutRubricDocument:
    config_id: UUID
    skill_name: str
    state: ScoutRubricState


@frozen
class ScoutRubricReservation:
    config: SignalScoutConfig
    created: bool
    # The completed batch the new request replaced. It is restored if the request cannot start.
    replaced_batch: ScoutRubricGeneration | None = None


class ScoutRubricNotFound(Exception):
    pass


class ScoutRubricGenerationLimitExceeded(Exception):
    pass


class ScoutRubricGenerationUnavailable(Exception):
    pass


def read_rubric_state(config: SignalScoutConfig) -> ScoutRubricState:
    if not config.rubrics:
        return ScoutRubricState(criteria=default_criteria())
    return ScoutRubricState.model_validate(config.rubrics)


def generation_expired(generation: ScoutRubricGeneration) -> bool:
    return generation.status in (ScoutRubricGenerationStatus.QUEUED, ScoutRubricGenerationStatus.RUNNING) and (
        timezone.now() - generation.requested_at > GENERATION_TIMEOUT
    )


def visible_rubric_state(config: SignalScoutConfig) -> ScoutRubricState:
    state = read_rubric_state(config)
    if state.generation and generation_expired(state.generation):
        state.generation.status = ScoutRubricGenerationStatus.FAILED
        state.generation.error = "Generation timed out. Try generating again."
    return state


def save_rubric(
    team_id: int, config_id: str, *, revision: int, criteria: list[ScoutRubricCriterion]
) -> SignalScoutConfig:
    with transaction.atomic():
        config = SignalScoutConfig.objects.for_team(team_id).select_for_update().get(id=config_id)
        state = read_rubric_state(config)
        if state.revision != revision:
            raise Conflict("These rubrics changed since you opened them. Reload before saving.")
        state.revision += 1
        state.criteria = criteria
        config.rubrics = state.model_dump(mode="json")
        config.save(update_fields=["rubrics", "updated_at"])
    return config


def reserve_generation(team_id: int, config_id: str) -> ScoutRubricReservation:
    with transaction.atomic():
        config = SignalScoutConfig.objects.for_team(team_id).select_for_update().get(id=config_id)
        state = read_rubric_state(config)
        generation = state.generation
        if (
            generation
            and not generation_expired(generation)
            and generation.status
            in (
                ScoutRubricGenerationStatus.QUEUED,
                ScoutRubricGenerationStatus.RUNNING,
            )
        ):
            return ScoutRubricReservation(config=config, created=False)
        state.generation = ScoutRubricGeneration(
            id=str(uuid4()), status=ScoutRubricGenerationStatus.QUEUED, requested_at=timezone.now()
        )
        config.rubrics = state.model_dump(mode="json")
        config.save(update_fields=["rubrics", "updated_at"])
    replaced_batch = generation if generation and generation.status == ScoutRubricGenerationStatus.COMPLETED else None
    return ScoutRubricReservation(config=config, created=True, replaced_batch=replaced_batch)


def update_generation(team_id: int, config_id: str, generation: ScoutRubricGeneration) -> bool:
    with transaction.atomic():
        config = SignalScoutConfig.objects.for_team(team_id).select_for_update().filter(id=config_id).first()
        if config is None:
            return False
        state = read_rubric_state(config)
        if (
            state.generation is None
            or state.generation.id != generation.id
            or state.generation.status not in (ScoutRubricGenerationStatus.QUEUED, ScoutRubricGenerationStatus.RUNNING)
        ):
            return False
        # A worker finishing late must not replace a newer draft or a user's saved criteria.
        expired = generation_expired(state.generation)
        if expired:
            state.generation.status = ScoutRubricGenerationStatus.FAILED
            state.generation.error = "Generation timed out. Try generating again."
            state.generation.completed_at = timezone.now()
        else:
            state.generation = generation
        config.rubrics = state.model_dump(mode="json")
        config.save(update_fields=["rubrics", "updated_at"])
        return not expired


def fail_generation(team_id: int, config_id: str, generation_id: str, message: str) -> None:
    with transaction.atomic():
        config = SignalScoutConfig.objects.for_team(team_id).select_for_update().filter(id=config_id).first()
        if config is None:
            return
        state = read_rubric_state(config)
        if (
            state.generation is None
            or state.generation.id != generation_id
            or state.generation.status not in (ScoutRubricGenerationStatus.QUEUED, ScoutRubricGenerationStatus.RUNNING)
        ):
            return
        state.generation.status = ScoutRubricGenerationStatus.FAILED
        state.generation.error = message
        state.generation.completed_at = timezone.now()
        config.rubrics = state.model_dump(mode="json")
        config.save(update_fields=["rubrics", "updated_at"])


def release_generation(
    team_id: int, config_id: str, generation_id: str, message: str, *, replaced_batch: ScoutRubricGeneration | None
) -> None:
    if replaced_batch is None:
        fail_generation(team_id, config_id, generation_id, message)
        return
    with transaction.atomic():
        config = SignalScoutConfig.objects.for_team(team_id).select_for_update().filter(id=config_id).first()
        if config is None:
            return
        state = read_rubric_state(config)
        if state.generation is None or state.generation.id != generation_id:
            return
        # The caller's error response reports the refusal, so the last completed batch stays visible.
        state.generation = replaced_batch
        config.rubrics = state.model_dump(mode="json")
        config.save(update_fields=["rubrics", "updated_at"])


def _to_document(config: SignalScoutConfig) -> ScoutRubricDocument:
    return ScoutRubricDocument(config_id=config.id, skill_name=config.skill_name, state=visible_rubric_state(config))


def get_scout_rubric(team_id: int, config_id: str) -> ScoutRubricDocument:
    try:
        config = SignalScoutConfig.objects.for_team(team_id).get(id=config_id)
    except (SignalScoutConfig.DoesNotExist, ValidationError, ValueError):
        raise ScoutRubricNotFound from None
    return _to_document(config)


def save_scout_rubric(
    team_id: int, config_id: str, *, revision: int, criteria: list[ScoutRubricCriterion]
) -> ScoutRubricDocument:
    return _to_document(save_rubric(team_id, config_id, revision=revision, criteria=criteria))


def generate_scout_rubric(team_id: int, config_id: str, *, user_id: int) -> ScoutRubricDocument:
    from products.signals.backend.scout_chat import (  # noqa: PLC0415 - keeps HTTP-only dependencies out of background rubric imports
        consume_daily_attempt,
        refund_daily_attempt,
    )

    reservation = reserve_generation(team_id, config_id)
    if not reservation.created:
        return _to_document(reservation.config)
    generation = read_rubric_state(reservation.config).generation
    assert generation is not None
    try:
        within_limit = consume_daily_attempt("signals_scout_rubrics", team_id, 20)
    except Exception:
        logger.exception(
            "signals.scout_rubrics.limit_check_failed",
            team_id=team_id,
            config_id=config_id,
            generation_id=generation.id,
        )
        release_generation(
            team_id,
            config_id,
            generation.id,
            "Generation could not start. Try again.",
            replaced_batch=reservation.replaced_batch,
        )
        raise ScoutRubricGenerationUnavailable from None
    if not within_limit:
        release_generation(
            team_id,
            config_id,
            generation.id,
            "Daily generation limit reached. Try tomorrow.",
            replaced_batch=reservation.replaced_batch,
        )
        raise ScoutRubricGenerationLimitExceeded
    try:
        from products.signals.backend.temporal.agentic.scout_rubrics import (  # noqa: PLC0415 - keeps Temporal off the route import path
            start_scout_rubric_generation,
        )

        start_scout_rubric_generation(
            sync_connect(),
            team_id=team_id,
            config_id=config_id,
            generation_id=generation.id,
            user_id=user_id,
        )
    except Exception:
        logger.exception(
            "signals.scout_rubrics.dispatch_failed",
            team_id=team_id,
            config_id=config_id,
            generation_id=generation.id,
        )
        try:
            refund_daily_attempt("signals_scout_rubrics", team_id)
        except Exception:
            logger.warning("signals.scout_rubrics.refund_failed", team_id=team_id, exc_info=True)
        release_generation(
            team_id,
            config_id,
            generation.id,
            "Generation could not start. Try again.",
            replaced_batch=reservation.replaced_batch,
        )
        raise ScoutRubricGenerationUnavailable from None
    return _to_document(reservation.config)
