from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class ReplayObservationAnchorSimilarity(TeamScopedRootMixin, models.Model):
    """An observation's similarity to every watch anchor sentence, keyed by anchor, so a viewer's own choice of
    anchors can be scored without reading the embedding back."""

    # No database constraint, so the recording delete, which removes observations in raw SQL, never fails on a row here.
    observation = models.OneToOneField(
        "replay_vision.ReplayObservation",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="+",
        db_constraint=False,
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    # Similarities from another anchor set do not compare, so readers ignore rows written under another version.
    anchor_version = models.PositiveSmallIntegerField()
    similarities = models.JSONField()

    class Meta:
        app_label = "replay_vision"
