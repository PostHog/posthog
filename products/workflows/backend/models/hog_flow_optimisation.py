from typing import Any

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel


class HogFlowOptimisation(TeamScopedRootMixin, UUIDTModel):
    """One row per workflow whose owner asked PostHog to suggest improvements to it.

    `enabled` is the opt-in: no row, or a disabled one, means no suggestion can be filed for the
    workflow, and the producer's work list leaves it out. Turning it off keeps the row, so
    "tried it and turned it off" stays answerable - that is the question a rollout has to answer,
    and a deleted row cannot.

    Who flipped it and when is in the workflow's activity log, next to the rest of that workflow's
    history, rather than as a pair of columns here that could only remember the last flip. Cadence
    and "when did it last look" belong to whoever schedules the producer, a Signals scout today.

    Behind the `self-optimising-workflows` flag.
    """

    # db_constraint=False on team: a real FK to a hot table takes a parent-table lock on creation;
    # enforcement stays app-level, as it does on WorkflowProposal.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    hog_flow = models.OneToOneField("workflows.HogFlow", on_delete=models.CASCADE, related_name="optimisation")

    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, help_text="When this workflow was first opted in.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Mirrors the workflow's team, as WorkflowProposal does.
        self.team_id = self.hog_flow.team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"HogFlowOptimisation {self.hog_flow_id} ({'on' if self.enabled else 'off'})"
