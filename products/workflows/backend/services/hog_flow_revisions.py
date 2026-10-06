from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.workflows.backend.facade.contracts import (
    WorkflowDraftChanged,
    WorkflowDraftExists,
    WorkflowRevision,
    WorkflowRevisionNotFound,
    WorkflowRevisionSummary,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.services.workflow_proposals import unstage_proposals_for_flow


def count_revisions(hog_flow_id: UUID) -> int:
    return HogFlowRevision.objects.filter(hog_flow_id=hog_flow_id).count()


def list_revisions(hog_flow_id: UUID, *, offset: int, limit: int) -> list[WorkflowRevisionSummary]:
    # Content is fetched per version via get_revision, so the list stays light.
    revisions = (
        HogFlowRevision.objects.filter(hog_flow_id=hog_flow_id)
        .order_by("-version")
        .select_related("created_by")
        .defer("content")[offset : offset + limit]
    )
    return [
        WorkflowRevisionSummary(version=r.version, created_at=r.created_at, created_by=r.created_by) for r in revisions
    ]


def get_revision(*, hog_flow_id: UUID, version: int) -> WorkflowRevision | None:
    revision = HogFlowRevision.objects.filter(hog_flow_id=hog_flow_id, version=version).first()
    if revision is None:
        return None
    return WorkflowRevision(
        version=revision.version,
        created_at=revision.created_at,
        created_by=revision.created_by,
        content=revision.content,
    )


def restore_revision(
    *, hog_flow_id: UUID, version: int, overwrite: bool, expected_draft_updated_at: datetime | None
) -> None:
    with transaction.atomic():
        # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance, locked for update)
        locked = HogFlow.objects.select_for_update().get(pk=hog_flow_id)
        try:
            revision = HogFlowRevision.objects.get(hog_flow_id=locked.pk, version=version)
        except HogFlowRevision.DoesNotExist:
            raise WorkflowRevisionNotFound()
        if locked.draft and not overwrite:
            raise WorkflowDraftExists()
        # Overwrite fencing: the client confirms against the draft stamp it saw. A draft staged
        # or edited between the confirmation dialog and this call carries a different stamp, and
        # overwriting it would lose unpublished content that no revision snapshots.
        if (
            locked.draft
            and expected_draft_updated_at is not None
            and locked.draft_updated_at != expected_draft_updated_at
        ):
            raise WorkflowDraftChanged()
        locked.draft = dict(revision.content)
        locked.draft_updated_at = timezone.now()
        unstage_proposals_for_flow(locked)
        # Revision snapshots carry no secrets (they're stripped before snapshotting), so the
        # restored draft re-attaches from the live encrypted_inputs on the follow-up publish.
        # Clear any stale draft secrets from a prior draft so they can't bleed into this one.
        locked.draft_encrypted_inputs = None
        locked.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])
