from django.db import models

from posthog.models.utils import UUIDModel


class ReplayObservationLabel(UUIDModel):
    """The team's shared judgement on whether a scanner scored a session correctly, with optional feedback.

    One label per observation: any editor can set or change it and everyone sees the same value. These labels
    feed scanner prompt improvement.
    """

    observation = models.OneToOneField(
        "replay_vision.ReplayObservation", on_delete=models.CASCADE, related_name="label"
    )
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    is_correct = models.BooleanField(help_text="True if the scanner scored this session correctly, false if not.")
    feedback = models.TextField(
        blank=True,
        default="",
        help_text="Why the scanner got it wrong / what it should have concluded. Empty for correct labels.",
    )
    # Last user to set or edit the shared label; nulled out rather than cascade-deleted if that user is removed.
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
