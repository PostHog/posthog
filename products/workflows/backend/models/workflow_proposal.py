from typing import Any

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDTModel


class WorkflowProposal(TeamScopedRootMixin, UUIDTModel):
    """A change to a workflow that an agent proposes and a human resolves.

    Approving one stages its content into the workflow's `draft` — the same move as restoring a
    revision — so nothing here can reach the live config without a human publishing it.

    Prototype behind the `self-optimising-workflows` flag. The producer is eventually a PostHog
    Autonomy Scout, which is why provenance is a created_via/source triple rather than an
    agent-vs-human flag, and why no field assumes the workflow page is the only reader.
    """

    class Status(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        APPLIED = "applied", "Applied"

    class CreatedVia(models.TextChoices):
        """How the proposal reached us. Values mirror `ExternalDataSource.CreatedVia`."""

        WEB = "web", "Web"
        API = "api", "API"
        MCP = "mcp", "MCP"
        SELF_DRIVING = "self_driving", "Self-driving"

    class SourceType(models.TextChoices):
        """What kind of producer authored it. The transport tells us `created_via`, but it can't
        tell a proactive Scout from a Responder reacting to one signal, so this half is declared."""

        SCOUT = "scout", "Scout"
        RESPONDER = "responder", "Responder"
        HUMAN = "human", "Human"
        STUB = "stub", "Stub generator"

    OPEN_STATUSES = (Status.SUGGESTED,)

    class Meta:
        constraints = [
            # An MCP retry or a re-emitted finding resolves to the same proposal instead of stacking
            # duplicates in a human's queue. Only fenced when the producer named itself.
            models.UniqueConstraint(
                fields=["hog_flow", "source_id"],
                condition=models.Q(source_id__isnull=False),
                name="unique_workflow_proposal_source",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "hog_flow", "status"], name="workflow_proposal_status_idx"),
        ]

    # db_constraint=False on team/created_by/resolved_by: a real FK constraint to a hot table
    # (posthog_team, posthog_user) takes a parent-table lock on creation; enforcement stays app-level.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.CASCADE, related_name="proposals")

    title = models.CharField(max_length=200, help_text="Short summary of the proposed change.")
    rationale = models.TextField(help_text="Why the producer thinks this change is worth making.")
    content = models.JSONField(
        help_text=(
            "The proposed change as a partial workflow content snapshot — only the fields it changes "
            "(actions, edges, trigger, conversion, exit_condition, variables). Approving merges it over "
            "the live content to build the staged draft."
        )
    )
    step_id = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text=(
            "The workflow step this is about, when it is about one. The evidence and the outcome both "
            "read metrics for this step, so a change to one email in a sequence is not measured against "
            "every other email in it."
        ),
    )
    base_version = models.IntegerField(
        help_text="Live workflow version this was authored against. Drives a staleness warning, not a block."
    )
    evidence = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "The numbers behind the proposal: the metric, its current and target value, the window, and "
            "the query that produced them."
        ),
    )

    status = models.CharField(max_length=20, choices=Status, default=Status.SUGGESTED)
    created_via = models.CharField(
        max_length=20,
        choices=CreatedVia,
        help_text="How the proposal was created. Derived from the request, never set by the caller.",
    )
    source_type = models.CharField(
        max_length=20, choices=SourceType, help_text="What kind of producer authored the proposal."
    )
    source_id = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text="Stable id of the producing agent run or finding, e.g. 'run:<run id>:finding:<finding id>'.",
    )

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="resolved_workflow_proposals",
    )
    resolution_note = models.TextField(blank=True, default="")
    applied_version = models.IntegerField(
        null=True, blank=True, help_text="Workflow version the approved change went live as."
    )

    def save(self, *args: Any, **kwargs: Any) -> None:
        # A proposal's tenant scope always mirrors its workflow's, as HogFlowRevision's does: a
        # mismatched (team, hog_flow) pair would leak the proposal into the wrong team's queue,
        # since fail-closed reads filter on this row's team_id, not the workflow's.
        self.team_id = self.hog_flow.team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"WorkflowProposal {self.hog_flow_id} ({self.status}): {self.title}"
