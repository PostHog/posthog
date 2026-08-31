from typing import Any

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel


class HogFlowOptimisation(TeamScopedRootMixin, UUIDTModel):
    """One row per workflow whose owner asked PostHog to suggest improvements to it.

    The row is the opt-in and nothing else: no row means nothing reads the workflow, so a producer
    costs nothing for workflows nobody asked about. Cadence lives with whoever schedules the
    producer - a Signals scout config today - so it is deliberately not repeated here.

    Prototype behind the `self-optimising-workflows` flag.
    """

    class Meta:
        indexes = [
            # The producer's work list: which of a team's workflows are in scope.
            models.Index(fields=["team", "hog_flow"], name="hog_flow_optimisation_team_idx"),
        ]

    # db_constraint=False on team/enabled_by: a real FK to a hot table takes a parent-table lock on
    # creation; enforcement stays app-level, as it does on WorkflowProposal.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    hog_flow = models.OneToOneField("workflows.HogFlow", on_delete=models.CASCADE, related_name="optimisation")

    enabled_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    enabled_at = models.DateTimeField(auto_now_add=True)

    last_run_at = models.DateTimeField(
        null=True, blank=True, help_text="When a producer last read this workflow's metrics."
    )

    def save(self, *args: Any, **kwargs: Any) -> None:
        # The opt-in's tenant scope always mirrors its workflow's, as WorkflowProposal's does: a
        # mismatched pair would hand one team's workflow to another team's producer.
        self.team_id = self.hog_flow.team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"HogFlowOptimisation {self.hog_flow_id}"
