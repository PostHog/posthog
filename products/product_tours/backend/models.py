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
