from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ReplayExperimentSynthesisStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class ReplayExperimentSynthesis(TeamScopedRootMixin, UUIDModel):
    """One synthesis run over an experiment scanner's summaries: what users in each variant do differently.

    Themes are shared across variants, so a count like "11 of 31 test vs 2 of 34 control" is computable.
    Every count comes from matching summaries to themes, never from the model's own text. A run covers
    one `scanner_version`, so a prompt edit never mixes summaries written with a different focus.
    """

    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner", on_delete=models.CASCADE, related_name="experiment_syntheses"
    )
    # db_constraint=False: the migration policy blocks real FK constraints to the hot posthog_team/posthog_user tables.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    scanner_version = models.PositiveIntegerField(help_text="The scanner version whose summaries this run covered.")
    status = models.CharField(
        max_length=16, choices=ReplayExperimentSynthesisStatus.choices, default=ReplayExperimentSynthesisStatus.RUNNING
    )
    observations_considered = models.JSONField(
        default=dict, help_text="Summaries the run read per variant, `{variant: n}`: the denominator of each count."
    )
    themes = models.JSONField(
        default=list,
        help_text="Themes shared across variants: `[{key, description, counts_by_variant, example_observation_ids}]`.",
    )
    digests = models.JSONField(
        default=dict, help_text="Each variant's 3 to 5 digest lines: `{variant: [{theme_key, statement, count}]}`."
    )
    differences = models.JSONField(
        default=list, help_text="What differs between variants: `[{statement, theme_key, counts: {variant: n}}]`."
    )
    error = models.TextField(blank=True, default="", help_text="Why the run failed, when it did.")
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
        help_text="Who asked for the run; null for a scheduled refresh.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    computed_at = models.DateTimeField(null=True, blank=True, help_text="When the run finished.")

    class Meta:
        constraints = [
            # One run in flight per scanner, so starting a refresh while one runs is a no-op.
            models.UniqueConstraint(
                fields=["scanner"],
                condition=models.Q(status="running"),
                name="rves_one_running_per_scanner",
            ),
        ]
        indexes = [
            models.Index(fields=["scanner", "created_at"], name="rves_scanner_created_idx"),
        ]

    def save(self, *args, **kwargs) -> None:
        # Tenant invariant: synthesis.team_id must match scanner.team_id.
        if self._state.adding:
            scanner_team_id = self.scanner.team_id
            if self.team_id and self.team_id != scanner_team_id:
                raise ValueError(
                    f"ReplayExperimentSynthesis.team_id ({self.team_id}) must match scanner.team_id ({scanner_team_id})"
                )
            self.team_id = scanner_team_id
        super().save(*args, **kwargs)
