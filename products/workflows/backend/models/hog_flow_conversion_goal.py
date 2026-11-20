from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class HogFlowConversionGoal(TeamScopedRootMixin, UUIDModel):
    """Every compiled conversion goal a workflow has had live. A run keeps the goal it started with, so
    the event matcher checks events against these, not only the workflow's current goal."""

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["hog_flow", "goal_hash"], name="unique_hogflow_conversion_goal"),
        ]
        indexes = [
            models.Index(fields=["last_live_at"], name="hogflow_conv_goal_live"),
            models.Index(fields=["created_at"], name="hogflow_conv_goal_created"),
        ]

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.CASCADE, related_name="conversion_goals")
    goal_hash = models.CharField(max_length=64, help_text="sha256 of the goal's canonical JSON.")
    goal = models.JSONField(help_text="The goal as a run saves it: {properties?: bytecode, events?: bytecode[]}.")
    event_names = models.JSONField(
        null=True,
        blank=True,
        help_text="Every event name the goal can match, so the matcher skips other events without running it. "
        "Null when it can match any event.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_live_at = models.DateTimeField(
        help_text="The last time the workflow was live with this goal. Runs keep it for at most the longest "
        "conversion window after that."
    )

    def __str__(self) -> str:
        return f"HogFlowConversionGoal {self.hog_flow_id} {self.goal_hash}"
