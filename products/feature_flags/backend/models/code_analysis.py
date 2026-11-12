from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class FeatureFlagCodeAnalysis(TeamScopedRootMixin, UUIDModel):
    """One request to find where a flag is checked in a repository and what each branch runs.

    The work runs as a read-only Tasks run. This row only points at it; the structured result lives
    in that run's output and is read through the tasks facade. The newest row for a flag is the
    analysis the flag page shows.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE lock on
    # posthog_team (a hot table) while migrating. No standalone index: the index below leads on team.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    # Keeps its own index because a flag delete cascades here by feature_flag_id alone.
    feature_flag = models.ForeignKey(
        "feature_flags.FeatureFlag", on_delete=models.CASCADE, related_name="code_analyses"
    )
    # A bare UUID, not a FK: tasks is an isolated product, so its rows are read through its facade.
    task_id = models.UUIDField()
    # GitHub repository (`org/repo`) the run analyzed, in GitHub's casing.
    repository = models.CharField(max_length=255)
    # The Tasks run that opens a pull request removing the flag's checks found by this analysis.
    cleanup_task_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "feature_flag", "-created_at"], name="ff_code_analysis_latest_idx"),
        ]

    def __str__(self) -> str:
        return f"FeatureFlagCodeAnalysis(team={self.team_id}, flag={self.feature_flag_id}, task={self.task_id})"
