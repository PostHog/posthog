"""Exported enums for ml_inference."""

from enum import StrEnum


class DecisionQuestionType(StrEnum):
    NOUL = "noul"
    CHOICE = "choice"
    SCORE = "score"
