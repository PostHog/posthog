import uuid

from django.db import models
from django.db.models import Q


class ProductTourManager(models.Manager):
    """Default manager that excludes archived tours."""

    def get_queryset(self):
        return super().get_queryset().filter(archived=False)


class ProductTour(models.Model):
    """A product tour guides users through application features."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="product_tours",
        related_query_name="product_tour",
    )

    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")

    internal_targeting_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="product_tours_internal_targeting_flag",
        related_query_name="product_tour_internal_targeting_flag",
    )

    linked_surveys = models.ManyToManyField(
        "posthog.Survey",
        blank=True,
        related_name="product_tours",
        related_query_name="product_tour",
    )

    content = models.JSONField(default=dict, blank=True)

    auto_launch = models.BooleanField(default=False)

    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_tours_created",
    )
    updated_at = models.DateTimeField(auto_now=True)

    archived = models.BooleanField(default=False)

    objects = ProductTourManager()
    all_objects: models.Manager["ProductTour"] = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=Q(archived=False),
                name="unique_product_tour_name_per_team",
            )
        ]
        indexes = [
            models.Index(fields=["team", "archived"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.id})"

    def get_analytics_metadata(self) -> dict:
        steps = self.content.get("steps", []) if self.content else []
        tour_type = self.content.get("type", "tour") if self.content else "tour"
        conditions = self.content.get("conditions", {}) if self.content else {}

        if tour_type == "announcement" and steps:
            first_step_type = steps[0].get("type")
            if first_step_type == "banner":
                tour_type = "banner"
            elif first_step_type == "modal":
                tour_type = "modal_announcement"

        return {
            "tour_id": str(self.id),
            "tour_name": self.name,
            "tour_type": tour_type,
            "step_count": len(steps),
            "has_targeting": self.internal_targeting_flag is not None,
            "has_survey_steps": any(s.get("survey") for s in steps),
            "auto_launch": self.auto_launch,
            "display_frequency": self.content.get("displayFrequency") if self.content else None,
            "has_url_condition": bool(conditions.get("url")),
            "url_match_type": conditions.get("urlMatchType"),
            "has_delay": bool(conditions.get("autoShowDelaySeconds")),
            "has_selector_condition": bool(conditions.get("selector")),
            "has_action_triggers": bool(conditions.get("actions", {}).get("values")),
            "has_event_triggers": bool(conditions.get("events", {}).get("values")),
        }
