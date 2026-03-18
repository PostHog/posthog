from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.core_event import CoreEvent
from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class MarketingAnalyticsGoalMapping(UUIDModel):
    """
    Maps a CoreEvent to Marketing Analytics with optional UTM field mappings.

    This model enables Marketing Analytics to use shared CoreEvents while adding
    marketing-specific configuration like schema_map for data warehouse goals.
    """

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="marketing_analytics_goal_mappings",
    )

    core_event = models.ForeignKey(
        CoreEvent,
        on_delete=models.CASCADE,  # Automatic cascade delete when core event is deleted
        related_name="marketing_goal_mappings",
    )

    # UTM field mappings - required for DataWarehouseNode, optional otherwise
    # Structure: {"utm_campaign_name": "campaign", "utm_source_name": "source"}
    schema_map = models.JSONField(
        default=dict,
        null=True,
        blank=True,
        help_text="UTM field mappings for data warehouse goals",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_marketinganalyticsgoalmapping"
        verbose_name = "Marketing Analytics Goal Mapping"
        verbose_name_plural = "Marketing Analytics Goal Mappings"
        unique_together = [["team", "core_event"]]
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"MarketingGoalMapping({self.team_id}, {self.core_event_id})"

    def clean(self) -> None:
        """Validate the model."""
        super().clean()

        # Validate schema_map structure
        if self.schema_map:
            if not isinstance(self.schema_map, dict):
                raise ValidationError("schema_map must be a dictionary")

            for key, val in self.schema_map.items():
                if not isinstance(key, str):
                    raise ValidationError(f"schema_map key '{key}' must be a string")
                if val is not None and not isinstance(val, str):
                    raise ValidationError(f"schema_map value for '{key}' must be a string or None")

        # For DataWarehouseNode, schema_map is required with UTM fields
        if self.core_event_id:
            try:
                if self.core_event.filter.get("kind") == "DataWarehouseNode":
                    if not self.schema_map:
                        raise ValidationError(
                            "schema_map is required for DataWarehouseNode goals. "
                            "Please specify utm_campaign_name and utm_source_name field mappings."
                        )
                    if "utm_campaign_name" not in self.schema_map:
                        raise ValidationError("schema_map must include 'utm_campaign_name' for DataWarehouseNode goals")
                    if "utm_source_name" not in self.schema_map:
                        raise ValidationError("schema_map must include 'utm_source_name' for DataWarehouseNode goals")
            except CoreEvent.DoesNotExist:
                pass  # Will be caught by FK constraint

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)
