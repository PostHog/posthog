"""Exported enums for ml_inference."""

from django.db import models


class DecisionQuestionType(models.TextChoices):
    NOUL = "noul", "Yes or no"
    CHOICE = "choice", "Multiple choice"
    SCORE = "score", "Rating scale"
