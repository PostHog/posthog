from django.db import models


class ClusteringConfig(models.Model):
    """Team-level configuration for LLM analytics clustering filters."""

    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="clustering_config",
    )

    # Property filters applied to both summarization and clustering pipelines
    event_filters = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "llm_analytics"

    def __str__(self):
        return f"ClusteringConfig for team {self.team_id}"
