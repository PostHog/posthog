from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.models.team import Team
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


DEFAULT_LEVEL_SPECS = (
    ("Default - traces", "trace"),
    ("Default - generations", "generation"),
    ("Default - evaluations", "evaluation"),
)


@receiver(post_save, sender=Team)
def create_default_clustering_jobs_for_new_team(sender, instance: Team, created: bool, **kwargs) -> None:
    """Auto-create ``Default - <level>`` rows for each of the three analysis levels when
    a new Team is created, so clustering is available end-to-end without the user having
    to open the admin modal.

    Why this is safe:

    - ``ClusteringJobViewSet.perform_create`` flips the matching ``Default - <level>`` row
      to ``enabled=False`` when a user creates a custom job for the same level, so the
      default and custom scopes don't both run for a level the user has customized.
    - ``ignore_conflicts=True`` against the ``(team, name)`` unique constraint makes the
      signal idempotent and covers the race with backfill migrations during deploy.
    - Runs only when ``created=True``, so it fires once per team lifetime.
    """
    if not created:
        return

    ClusteringJob.objects.bulk_create(
        [
            ClusteringJob(
                team=instance,
                name=name,
                analysis_level=level,
                event_filters=[],
                enabled=True,
            )
            for name, level in DEFAULT_LEVEL_SPECS
        ],
        ignore_conflicts=True,
    )
