"""Django models for today. Keep models thin; logic lives in logic/."""

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import HighlightsStatus, NewsStatus


class TodayHighlights(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user_id = models.BigIntegerField()
    local_day = models.DateField()
    key = models.CharField(max_length=32)
    pins_key = models.CharField(max_length=32, default="", db_default="", blank=True)
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


class TodayPulsePins(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user_id = models.BigIntegerField()
    pins = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["team_id", "user_id"], name="today_pulse_pins_unique_user"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {len(self.pins)} pins"


class NewsPeriod(models.TextChoices):
    WEEK = "week", "Week"
    DAY = "day", "Day"


class TodayNewsEdition(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    period = models.CharField(max_length=8, choices=NewsPeriod.choices, default=NewsPeriod.WEEK.value)
    period_start = models.DateField()
    status = models.CharField(max_length=16, choices=NewsStatus.choices, default=NewsStatus.COMPUTING.value)
    skip_reason = models.CharField(max_length=32, blank=True, default="")
    facts = models.JSONField(default=list)
    content = models.JSONField(default=dict)
    model = models.CharField(max_length=64, blank=True, default="")
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["team_id", "period", "period_start"], name="today_news_one_per_period"),
        ]

    def __str__(self) -> str:
        return f"{self.period_start} {self.status}"
