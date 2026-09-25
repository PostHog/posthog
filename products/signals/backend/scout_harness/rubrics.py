from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from django.db import models, transaction
from django.utils import timezone

from pydantic import BaseModel, ConfigDict, Field

from posthog.exceptions import Conflict

from products.signals.backend.models import SignalScoutConfig

RUBRIC_TEAM_ID = 2
MAX_CRITERIA = 30
MAX_SUGGESTIONS = 10
GENERATION_TIMEOUT = timedelta(minutes=30)


class ScoutRubricSource(models.TextChoices):
    DEFAULT = "default", "Default"
    CUSTOM = "custom", "Custom"


class ScoutRubricGenerationStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class ScoutRubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    pass_condition: str = Field(min_length=1, max_length=2000)
    applicability: str = Field(min_length=1, max_length=1000)
    enabled: bool
    source: ScoutRubricSource


class ScoutRubricSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    pass_condition: str = Field(min_length=1, max_length=2000)
    applicability: str = Field(min_length=1, max_length=1000)


class ScoutRubricSuggestionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=2000)
    suggestions: list[ScoutRubricSuggestion] = Field(max_length=MAX_SUGGESTIONS)


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


def default_criteria() -> list[ScoutRubricCriterion]:
    definitions = [
        (
            "evidence",
            "Claims supported by evidence",
            "Check whether conclusions follow from the sources the scout actually inspected.",
            "Material claims cite relevant evidence, distinguish observations from guesses, and state missing evidence.",
            "When the scout makes a factual claim or recommends an action.",
        ),
        (
            "clarity",
            "Clear findings",
            "Check whether a reader can understand the finding and why it matters.",
            "The output identifies the issue and affected area concisely, with readable supporting detail.",
            "When the scout produces an output intended for a person.",
        ),
        (
            "actionability",
            "Useful next step",
            "Check whether a finding gives its reader a practical way to proceed.",
            "The output names a concrete next action or decision, with enough context to carry it out.",
            "When the scout is expected to recommend action; informational updates may be not applicable.",
        ),
        (
            "priority",
            "Priority matches impact",
            "Check whether urgency follows from demonstrated impact and scope.",
            "The priority follows the stated project policy and available impact evidence without exaggerating reach.",
            "When the scout assigns or recommends a priority.",
        ),
        (
            "instructions",
            "Required instructions followed",
            "Check whether the scout follows its assignment and required skills.",
            "The trace shows required skills were consulted and task-specific constraints were respected.",
            "When the assignment requires skills or constrains the scope of the work; missing trace evidence is unknown.",
        ),
        (
            "memory",
            "Relevant history considered",
            "Check whether the scout uses available history to avoid duplicate or outdated findings.",
            "The scout checks relevant existing memory or reports when needed and explains material changes to known issues.",
            "When relevant history exists or the assignment requires a history check; extra writes are not required.",
        ),
    ]
    return [
        ScoutRubricCriterion(
            id=f"default-{key}",
            title=title,
            description=description,
            pass_condition=condition,
            applicability=applicability,
            enabled=True,
            source=ScoutRubricSource.DEFAULT,
        )
        for key, title, description, condition, applicability in definitions
    ]


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


def reserve_generation(team_id: int, config_id: str) -> tuple[SignalScoutConfig, bool]:
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
            return config, False
        state.generation = ScoutRubricGeneration(
            id=str(uuid4()), status=ScoutRubricGenerationStatus.QUEUED, requested_at=timezone.now()
        )
        config.rubrics = state.model_dump(mode="json")
        config.save(update_fields=["rubrics", "updated_at"])
    return config, True


def update_generation(team_id: int, config_id: str, generation: ScoutRubricGeneration) -> bool:
    with transaction.atomic():
        config = SignalScoutConfig.objects.for_team(team_id).select_for_update().filter(id=config_id).first()
        if config is None:
            return False
        state = read_rubric_state(config)
        if state.generation is None or state.generation.id != generation.id:
            return False
        # A worker finishing late must not replace a newer draft or a user's saved criteria.
        state.generation = generation
        config.rubrics = state.model_dump(mode="json")
        config.save(update_fields=["rubrics", "updated_at"])
        return True


def fail_generation(team_id: int, config_id: str, generation_id: str, message: str) -> None:
    with transaction.atomic():
        config = SignalScoutConfig.objects.for_team(team_id).select_for_update().filter(id=config_id).first()
        if config is None:
            return
        state = read_rubric_state(config)
        if state.generation is None or state.generation.id != generation_id:
            return
        state.generation.status = ScoutRubricGenerationStatus.FAILED
        state.generation.error = message
        state.generation.completed_at = timezone.now()
        config.rubrics = state.model_dump(mode="json")
        config.save(update_fields=["rubrics", "updated_at"])
