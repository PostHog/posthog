from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

MAX_CRITERIA = 30
MAX_SUGGESTIONS = 10


class ScoutRubricSource(StrEnum):
    DEFAULT = "default"
    CUSTOM = "custom"


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
