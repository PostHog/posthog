from django.db import models

from posthog.models.team import Team


class TeamReplayVisionConfig(models.Model):
    """Per-team Replay Vision state. Lives on a Team extension so posthog_team is never ALTERed."""

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on posthog_team while
    # migrating, stalling writes under traffic.
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+")

    search_suggestions = models.JSONField(
        default=list,
        blank=True,
        help_text="Example searches for the cross-scanner Search tab, drawn from findings across the team's scanners.",
    )
    search_suggestions_sources = models.JSONField(
        default=list,
        blank=True,
        help_text="Ids of the scanners whose observations fed `search_suggestions`. A viewer sees the phrases only "
        "when they can read every one of them.",
    )
    search_suggestions_watermark = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Created time of the newest observation the stored phrases read.",
    )
    search_suggestions_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "replay_vision"
