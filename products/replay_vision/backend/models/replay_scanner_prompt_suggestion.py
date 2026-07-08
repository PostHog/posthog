from django.db import models

from posthog.models.utils import UUIDModel


class SuggestionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPLIED = "applied", "Applied"
    DISMISSED = "dismissed", "Dismissed"
    SUPERSEDED = "superseded", "Superseded"
    # The model reviewed the ratings and found the current prompt already handles them well.
    NO_CHANGE = "no_change", "No change"


class ReplayScannerPromptSuggestion(UUIDModel):
    """An AI-suggested rewrite of a scanner's prompt, generated from the team's thumbs up/down ratings.

    The newest row is the scanner's current recommendation; older rows are kept as history. A suggestion
    records the rating set it was generated from (`labels_fingerprint`), so a changed rating set marks
    it stale and triggers a refresh.
    """

    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="prompt_suggestions"
    )
    # db_constraint=False: the migration policy blocks real FK constraints to the hot posthog_team/posthog_user tables.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    suggested_prompt = models.TextField(help_text="The full rewritten prompt, ready to apply to the scanner.")
    base_prompt = models.TextField(
        blank=True, default="", help_text="The scanner prompt this suggestion was generated against, for diffing."
    )
    rationale = models.TextField(
        blank=True, default="", help_text="What the rewrite changed and why, grounded in the ratings."
    )
    status = models.CharField(max_length=16, choices=SuggestionStatus.choices, default=SuggestionStatus.PENDING)
    based_on_up = models.PositiveIntegerField(default=0, help_text="Thumbs-up ratings the suggestion was based on.")
    based_on_down = models.PositiveIntegerField(default=0, help_text="Thumbs-down ratings the suggestion was based on.")
    # Hash of the rated set at generation time; a different current fingerprint means the suggestion is stale.
    labels_fingerprint = models.CharField(max_length=64, blank=True, default="")
    scanner_version = models.PositiveIntegerField(
        default=0, help_text="The scanner version whose prompt this suggestion was generated against."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Null for automatic refreshes; set when a user clicked regenerate.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )

    def save(self, *args, **kwargs) -> None:
        # Tenant invariant: suggestion.team_id must match scanner.team_id.
        if self._state.adding:
            scanner_team_id = self.scanner.team_id
            if self.team_id and self.team_id != scanner_team_id:
                raise ValueError(
                    f"ReplayScannerPromptSuggestion.team_id ({self.team_id}) must match scanner.team_id "
                    f"({scanner_team_id})"
                )
            self.team_id = scanner_team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.scanner_id} [{self.status}]"
