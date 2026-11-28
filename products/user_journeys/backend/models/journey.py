"""A saved, ordered user flow that the product measures as a funnel.

The row holds the definition only. Conversion results and replay runs belong to whatever computes
them, so those can change without a migration here.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.user_journeys.backend.facade.contracts import (
    DEFAULT_CONVERSION_WINDOW_MINUTES,
    MAX_CONVERSION_WINDOW_MINUTES,
    MIN_CONVERSION_WINDOW_MINUTES,
)
from products.user_journeys.backend.facade.enums import JourneySource


class Journey(TeamScopedRootMixin, UUIDModel):
    Source = JourneySource

    # No database constraint: creating one takes a lock on `posthog_team` that queues behind
    # live writes. Django still cascades the delete in Python.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # No database constraint, for the same reason on `posthog_user`.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="", db_default="")
    # The shape is the `JourneyStep` contract list. The facade validates it on every read and write.
    steps = models.JSONField()
    conversion_window_minutes = models.PositiveIntegerField(
        default=DEFAULT_CONVERSION_WINDOW_MINUTES,
        db_default=DEFAULT_CONVERSION_WINDOW_MINUTES,
        validators=[MinValueValidator(MIN_CONVERSION_WINDOW_MINUTES), MaxValueValidator(MAX_CONVERSION_WINDOW_MINUTES)],
    )
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.MANUAL.value, db_default=Source.MANUAL.value
    )
