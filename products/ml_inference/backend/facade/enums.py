"""Exported enums for ml_inference."""

from posthog.enums import LabeledStrEnum


class DecisionQuestionType(LabeledStrEnum):
    NOUL = "noul", "Yes or no"
    CHOICE = "choice", "Multiple choice"
    SCORE = "score", "Rating scale"
