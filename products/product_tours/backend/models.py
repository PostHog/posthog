import uuid

from django.db import models
from django.db.models import Q


class ProductTour(models.Model):
    """The product tours product is retired. The model stays so that Django keeps cascading team,
    user, feature flag and survey deletes into its tables. A later migration removes the model
    and drops the tables."""

    # nosemgrep: prefer-uuid7-django-pk -- a retired model, and a new primary key default would need a migration.
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
        "feature_flags.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="product_tours_internal_targeting_flag",
        related_query_name="product_tour_internal_targeting_flag",
    )

    linked_flag = models.ForeignKey(
        "feature_flags.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="product_tours_linked_flag",
        related_query_name="product_tour_linked_flag",
        db_index=False,
    )

    linked_surveys = models.ManyToManyField(
        "surveys.Survey",
        blank=True,
        related_name="product_tours",
        related_query_name="product_tour",
    )

    content = models.JSONField(default=dict, blank=True)
    draft_content = models.JSONField(null=True, blank=True, default=None)

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
