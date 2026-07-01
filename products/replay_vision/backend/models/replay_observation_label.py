from django.db import models

from posthog.models.utils import UUIDModel


class ReplayObservationLabel(UUIDModel):
    """One user's judgement on whether a scanner scored a session correctly, with optional feedback."""

    observation = models.ForeignKey("replay_vision.ReplayObservation", on_delete=models.CASCADE, related_name="labels")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    is_correct = models.BooleanField(help_text="True if the scanner scored this session correctly, false if not.")
    feedback = models.TextField(
        blank=True,
        default="",
        help_text="Why the scanner got it wrong / what it should have concluded. Empty for correct labels.",
    )
    created_by = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["observation", "created_by"], name="replay_observation_label_unique_observation_user"
            ),
        ]
        indexes = [
            models.Index(fields=["observation"], name="rlol_observation_idx"),
        ]

    def save(self, *args, **kwargs) -> None:
        # Tenant invariant: label.team_id must match observation.team_id.
        if self._state.adding:
            observation_team_id = self.observation.team_id
            if self.team_id and self.team_id != observation_team_id:
                raise ValueError(
                    f"ReplayObservationLabel.team_id ({self.team_id}) must match observation.team_id "
                    f"({observation_team_id})"
                )
            self.team_id = observation_team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.observation_id} [{'correct' if self.is_correct else 'incorrect'}]"
