from django.db import models

from posthog.models.utils import UUIDModel


class ClusteringJob(UUIDModel):
    """A named clustering configuration for a team.

    Each job defines one analysis level (trace, generation, or evaluation) and one set of
    event filters.  A team may have up to MAX_JOBS_PER_TEAM jobs (see api.clustering_job).
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="clustering_jobs",
    )
    name = models.CharField(max_length=100)
    analysis_level = models.CharField(
        max_length=20,
        choices=[("trace", "trace"), ("generation", "generation"), ("evaluation", "evaluation")],
    )
    event_filters = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "llm_analytics"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_clustering_job_name_per_team",
            ),
        ]

    def __str__(self) -> str:
        return f"ClusteringJob(team={self.team_id}, name={self.name!r}, level={self.analysis_level})"
