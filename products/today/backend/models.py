"""Django models for today. Keep models thin; logic lives in logic/."""

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import HighlightsStatus


class TodayHighlights(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user_id = models.BigIntegerField()
    local_day = models.DateField()
    key = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=HighlightsStatus.choices, default=HighlightsStatus.COMPUTING.value)
    content = models.JSONField(default=dict)
    failed_sources = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)

    class Meta(ProductTeamModel.Meta):
        indexes = [
            models.Index(fields=["team_id", "user_id", "key", "-created_at"], name="today_highlights_key_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.local_day} {self.status}"
