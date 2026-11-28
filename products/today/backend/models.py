"""Django models for today. Keep models thin; logic lives in logic/."""

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import HighlightsStatus, HogAccessory, SeasonalActionKind, SeasonalItemIcon


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
    hidden = models.JSONField(default=list, db_default=[])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["team_id", "user_id"], name="today_pulse_pins_unique_user"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {len(self.pins)} pins"


class SeasonalCampaign(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    key = models.SlugField(
        max_length=100, unique=True, help_text="A new key starts everyone's progress and dismissal again."
    )
    is_active = models.BooleanField(default=False)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    reason = models.CharField(max_length=300, blank=True)
    badge = models.CharField(max_length=50, blank=True)
    bubble = models.CharField(max_length=100)
    done_title = models.CharField(max_length=200)
    done_description = models.TextField()
    accessories = ArrayField(
        models.CharField(max_length=32, choices=HogAccessory.choices),
        default=list,
        blank=True,
        size=4,
        help_text="Up to 4, separated by commas, for example xmas-hat,xmas-scarf.",
    )
    snow = models.BooleanField(default=False)
    lights = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.key


class SeasonalCampaignItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    campaign = models.ForeignKey(SeasonalCampaign, on_delete=models.CASCADE, related_name="items")
    key = models.SlugField(max_length=100, db_index=False)
    order = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=200)
    description = models.TextField()
    icon = models.CharField(max_length=32, choices=SeasonalItemIcon.choices, blank=True)
    action_kind = models.CharField(max_length=32, choices=SeasonalActionKind.choices)
    action_settings = models.JSONField(
        default=dict,
        blank=True,
        help_text='JSON for the action. Do it with PostHog AI: {"prompt": "..."}.',
    )

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["campaign", "key"], name="today_seasonal_item_unique_key"),
        ]

    def __str__(self) -> str:
        return f"{self.campaign_id} {self.key}"
