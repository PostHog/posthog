from django.db import models

from posthog.models.team import Team


class TeamReplayVisionConfig(models.Model):
    """Per-team Replay Vision state. Lives on a Team extension so posthog_team is never ALTERed."""

    # db_constraint=False: a real FK constraint takes SHARE ROW EXCLUSIVE on posthog_team while
    # migrating, stalling writes under traffic.
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+")

    learned_rules_watermark = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Update time of the newest observation rating the learned rules have read.",
    )
    learned_rules_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "replay_vision"
