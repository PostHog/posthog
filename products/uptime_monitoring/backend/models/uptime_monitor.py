"""A URL to check and how to check it.

The row holds no check results and no pointer to whatever runs the checks. Results belong to the
runner, so the runner can change without a migration here.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.uptime_monitoring.backend.facade.enums import UptimeMonitorMethod

MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 24 * 60 * 60
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 30


class UptimeMonitor(TeamScopedRootMixin, UUIDModel):
    Method = UptimeMonitorMethod

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
    url = models.URLField(max_length=2048)
    method = models.CharField(max_length=8, choices=Method.choices, default=Method.GET, db_default=Method.GET)
    interval_seconds = models.PositiveIntegerField(
        default=300,
        db_default=300,
        validators=[MinValueValidator(MIN_INTERVAL_SECONDS), MaxValueValidator(MAX_INTERVAL_SECONDS)],
    )
    timeout_seconds = models.PositiveIntegerField(
        default=10,
        db_default=10,
        validators=[MinValueValidator(MIN_TIMEOUT_SECONDS), MaxValueValidator(MAX_TIMEOUT_SECONDS)],
    )
    enabled = models.BooleanField(default=True, db_default=True)
