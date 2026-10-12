from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.workflows.backend.facade.enums import WorkflowIdeaSource, WorkflowIdeaStatus, WorkflowIdeaValueTier


class WorkflowIdea(TeamScopedRootMixin, UUIDModel):
    """A whole workflow PostHog suggests to a project, ready to become a draft.

    Accepting one creates a draft workflow from `definition`, so nothing reaches anyone until a person
    reviews the draft, picks a sender and enables it.
    """

    Status = WorkflowIdeaStatus
    Source = WorkflowIdeaSource
    ValueTier = WorkflowIdeaValueTier

    class Meta:
        constraints = [
            # Suggesting the same idea twice to one project would undo a dismissal.
            models.UniqueConstraint(fields=["team", "key"], name="unique_workflow_idea_key"),
        ]
        indexes = [
            models.Index(fields=["team", "status"], name="workflow_idea_status_idx"),
        ]

    # db_constraint=False: a real FK constraint to a hot table takes a parent-table lock on creation.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")

    key = models.CharField(max_length=200, help_text="Stable name of the idea within the project.")
    title = models.CharField(max_length=200, help_text="Short name of the suggested workflow.")
    rationale = models.TextField(help_text="Why this workflow is worth running, in one or two sentences.")
    value_tier = models.CharField(
        max_length=20,
        choices=ValueTier.choices,
        help_text="How close the workflow's goal is to revenue. Orders the ideas.",
    )
    evidence = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "The numbers behind the idea: trigger and goal events, the share who reach the goal with "
            "no message, the reachable audience, and when they were measured."
        ),
    )
    definition = models.JSONField(
        help_text=(
            "The workflow to create on accept, in the shape the workflows API takes: trigger, actions, "
            "edges, conversion and exit condition."
        )
    )
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL.value)
    source_ref = models.CharField(
        max_length=200, null=True, blank=True, help_text="The run or batch that produced the idea."
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUGGESTED.value)
    dismiss_reason = models.TextField(blank=True, default="", db_default="")
    hog_flow = models.ForeignKey(
        "workflows.HogFlow", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    def __str__(self) -> str:
        return f"WorkflowIdea {self.team_id}/{self.key} ({self.status})"
