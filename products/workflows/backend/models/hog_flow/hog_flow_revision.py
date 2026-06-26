from typing import TYPE_CHECKING, Final

from django.db import models

from posthog.models.utils import UUIDTModel

if TYPE_CHECKING:
    from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

# Content fields copied verbatim between a HogFlow and its revisions. These define what the
# workflow does, so a revision is a full snapshot of them.
CONTENT_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "description",
    "trigger",
    "trigger_masking",
    "conversion",
    "exit_condition",
    "edges",
    "actions",
    "abort_action",
    "variables",
    "billable_action_types",
)


class HogFlowRevision(UUIDTModel):
    """
    A versioned snapshot of a HogFlow's content. Each revision belongs to one HogFlow and carries
    a monotonic version number. A workflow's live config is its HogFlow.active_revision; in-progress
    edits accumulate on the single open draft revision until published.
    """

    class Meta:
        db_table = "posthog_hogflowrevision"
        indexes = [
            models.Index(fields=["hog_flow", "version"], name="hfr_flow_version_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "hog_flow", "version"], name="unique_revision_version"),
        ]

    class State(models.TextChoices):
        DRAFT = "draft"
        ACTIVE = "active"
        ARCHIVED = "archived"

    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.CASCADE, related_name="revisions")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    version = models.IntegerField()
    status = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True, default="")

    trigger = models.JSONField(default=dict)
    trigger_masking = models.JSONField(null=True, blank=True)
    conversion = models.JSONField(null=True, blank=True)
    exit_condition = models.CharField(max_length=100, default="exit_on_conversion")

    edges = models.JSONField(default=dict)
    actions = models.JSONField(default=dict)
    abort_action = models.CharField(max_length=400, null=True, blank=True)
    variables = models.JSONField(default=list, null=True, blank=True)

    billable_action_types = models.JSONField(default=list, null=True, blank=True)

    def __str__(self) -> str:
        return f"HogFlowRevision {self.hog_flow_id}/v{self.version} ({self.status})"


def sync_mirror_revision(hog_flow: "HogFlow") -> HogFlowRevision:
    """
    Phase 0 double-write: keep a single revision mirroring the workflow's live content so the
    revisions table stays consistent before anything reads from it. The workflow's content columns
    remain canonical; this reflects them (and its status) onto one revision and points
    active_revision at it while the workflow is active. The real draft/publish/versioning cycle
    replaces this in a later phase.
    """
    revision = hog_flow.revisions.order_by("version").first()
    if revision is None:
        revision = HogFlowRevision(hog_flow=hog_flow, team_id=hog_flow.team_id, version=hog_flow.version)

    for field in CONTENT_FIELDS:
        setattr(revision, field, getattr(hog_flow, field))
    revision.version = hog_flow.version
    revision.status = hog_flow.status
    revision.save()

    target_active_id = revision.id if hog_flow.status == HogFlowRevision.State.ACTIVE else None
    if hog_flow.active_revision_id != target_active_id:
        # .update() avoids re-firing the post_save reload signal for this bookkeeping write.
        type(hog_flow).objects.filter(pk=hog_flow.pk).update(active_revision_id=target_active_id)
        hog_flow.active_revision_id = target_active_id

    return revision
