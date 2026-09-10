from typing import Any

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel


class HogFlowRevision(TeamScopedRootMixin, UUIDTModel):
    """Append-only snapshot of a workflow's live content, written whenever the live config
    changes. Rollback copies a snapshot back into the draft; workers never read this table."""

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["hog_flow", "version"], name="unique_hogflow_revision_version"),
        ]

    # db_constraint=False on team/created_by: a real FK constraint to a hot table (posthog_team,
    # posthog_user) takes a parent-table lock on creation; enforcement stays app-level.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.CASCADE, related_name="revisions")
    version = models.IntegerField(help_text="Workflow version this snapshot was published as.")
    content = models.JSONField(
        help_text="Full snapshot of the workflow's content fields (actions, edges, trigger, etc.) at this version."
    )
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args: Any, **kwargs: Any) -> None:
        # A revision's tenant scope always mirrors its workflow's. A mismatched (team, hog_flow)
        # pair would leak the revision into the wrong team's history — fail-closed reads filter on
        # this row's team_id, not the workflow's.
        self.team_id = self.hog_flow.team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"HogFlowRevision {self.hog_flow_id} v{self.version}"
