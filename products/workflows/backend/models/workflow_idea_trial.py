from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class WorkflowIdeaTrial(TeamScopedRootMixin, UUIDModel):
    """One project's turn in a cohort of the workflow ideas scout.

    The scout runs only on projects a cohort enrolled, for a fixed number of days, and the cohort
    then rotates to the next projects most likely to adopt Workflows. A trial records why the project
    was picked and what it did with Workflows while the scout ran, so later cohorts can be picked on
    evidence.
    """

    class Segment(models.TextChoices):
        COMPETITOR = "competitor", "Sends through another messaging tool"
        STALLED = "stalled", "Started with Workflows and stalled"
        GREENFIELD = "greenfield", "Large and messages nobody"

    class Outcome(models.TextChoices):
        RUNNING = "running", "Running"
        ADOPTED = "adopted", "Launched a workflow"
        DRAFTED = "drafted", "Drafted a workflow"
        NO_CHANGE = "no_change", "No change"
        NOT_ENROLLED = "not_enrolled", "Not enrolled"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "cohort"], name="unique_workflow_idea_trial_cohort"),
        ]
        indexes = [
            models.Index(fields=["outcome", "ends_at"], name="workflow_idea_trial_open_idx"),
        ]

    # db_constraint=False: a real FK constraint to posthog_team takes a parent-table lock on creation.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    cohort = models.PositiveIntegerField()
    segment = models.CharField(max_length=20, choices=Segment)
    score = models.FloatField()
    # The candidate signals at selection time, so a cohort's picks can be audited after the data moves.
    selection = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome, default=Outcome.RUNNING)

    workflows_created = models.PositiveIntegerField(null=True, blank=True)
    workflows_launched = models.PositiveIntegerField(null=True, blank=True)
    billable_invocations = models.PositiveBigIntegerField(null=True, blank=True)

    def __str__(self) -> str:
        return f"WorkflowIdeaTrial team={self.team_id} cohort={self.cohort} ({self.outcome})"
