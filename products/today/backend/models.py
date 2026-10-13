"""Django models for today. Keep models thin; logic lives in logic/."""

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import BriefingStatus, BriefingTrigger, BriefingWriter


class DailyBriefing(ProductTeamModel):
    """One generation of a person's Today briefing. The page shows the day's newest ready one."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user_id = models.BigIntegerField()
    local_day = models.DateField()
    timezone = models.CharField(max_length=64)
    trigger = models.CharField(max_length=16, choices=[(t.value, t.value) for t in BriefingTrigger])
    status = models.CharField(
        max_length=16, choices=[(s.value, s.value) for s in BriefingStatus], default=BriefingStatus.COLLECTING.value
    )
    # The items the briefing names, with the facts its text rests on (`FactSheet`).
    facts = models.JSONField(default=dict)
    # The text the page shows (`BriefingContent`).
    content = models.JSONField(default=dict)
    writer = models.CharField(max_length=16, choices=[(w.value, w.value) for w in BriefingWriter], null=True)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    # The last time the person opened Today with this briefing; the schedule only serves recent viewers.
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta(ProductTeamModel.Meta):
        indexes = [
            models.Index(fields=["team_id", "user_id", "local_day", "-created_at"], name="today_briefing_day_idx"),
            models.Index(fields=["last_viewed_at"], name="today_briefing_viewed_idx"),
            models.Index(
                fields=["created_at"],
                name="today_briefing_pending_idx",
                condition=models.Q(status__in=["collecting", "writing"]),
            ),
        ]
        # One run per day at a time: two requests that both find no briefing must not both start a run.
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "user_id", "local_day"],
                condition=models.Q(status__in=["collecting", "writing"]),
                name="today_briefing_one_pending",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.local_day} {self.status}"
