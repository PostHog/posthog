from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class WebAnalyticsInteraction(TeamScopedRootMixin, UUIDModel):
    """First-party per-user counter of in-product Web analytics interactions, the source for the
    Explorer and Detective tracks. The product-usage events these tracks reward are captured to
    PostHog's own internal analytics instance, not the customer team's events table, so they can't be
    queried back — counting first-party here keeps the metric correct for every team."""

    DATA = "data"
    RECORDING = "recording"
    KIND_CHOICES = [(DATA, "data"), (RECORDING, "recording")]

    # No index on team alone: every read filters the full (team, user, kind) triple, which the
    # unique constraint below already serves.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_index=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    count = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_webanalyticsinteraction"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "kind"],
                name="unique_web_analytics_interaction_per_kind",
            ),
        ]
