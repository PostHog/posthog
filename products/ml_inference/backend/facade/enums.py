"""Exported enums for ml_inference."""

from django.db import models


class DecisionQuestionType(models.TextChoices):
    NOUL = "noul", "Yes or no"
    CHOICE = "choice", "Multiple choice"
    SCORE = "score", "Rating scale"


class SearchIntentSource(models.TextChoices):
    RULE = "rule", "Matched a value pattern"
    MODEL = "model", "Asked the decision model"
    SKIPPED = "skipped", "Not classified"
