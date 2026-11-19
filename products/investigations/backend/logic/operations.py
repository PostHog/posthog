from dataclasses import asdict
from uuid import UUID

from django.db import transaction

from posthog.models.utils import strict_fetch

from ..facade.contracts import (
    InvestigationConflict,
    InvestigationDocument,
    InvestigationNotFound,
    InvestigationSummary,
    SavedInvestigation,
)
from ..facade.enums import InvestigationStage
from ..models import Investigation


def summary(obj: Investigation) -> InvestigationSummary:
    return InvestigationSummary(
        id=obj.id,
        question=obj.document["question"],
        status=InvestigationStage(obj.document["status"]),
        revision=obj.revision,
        evidence_count=len(obj.document["evidence"]),
        run_count=len(obj.document["runs"]),
        updated_at=obj.updated_at,
        created_at=obj.created_at,
        created_by=obj.created_by_id,
    )


def saved(obj: Investigation) -> SavedInvestigation:
    return SavedInvestigation(**asdict(summary(obj)), document=obj.document)


def list_investigations(team_id: int, search: str, offset: int, limit: int) -> tuple[list[InvestigationSummary], int]:
    queryset = Investigation.objects.for_team(team_id).filter(deleted=False)
    if search:
        queryset = queryset.filter(document__question__icontains=search)
    count = queryset.count()
    rows = strict_fetch(queryset.order_by("-updated_at", "-id")[offset : offset + limit])
    return [summary(obj) for obj in rows], count


def get_investigation(team_id: int, id: UUID) -> SavedInvestigation:
    try:
        return saved(Investigation.objects.for_team(team_id).get(id=id, deleted=False))
    except Investigation.DoesNotExist as exc:
        raise InvestigationNotFound from exc


def create_investigation(team_id: int, user_id: int, document: InvestigationDocument) -> SavedInvestigation:
    return saved(
        Investigation.objects.for_team(team_id).create(
            team_id=team_id, created_by_id=user_id, document=document.model_dump(mode="json")
        )
    )


@transaction.atomic
def update_investigation(
    team_id: int, id: UUID, revision: int, document: InvestigationDocument | None, deleted: bool = False
) -> SavedInvestigation:
    try:
        obj = Investigation.objects.for_team(team_id).select_for_update().get(id=id, deleted=False)
    except Investigation.DoesNotExist as exc:
        raise InvestigationNotFound from exc
    if obj.revision != revision:
        raise InvestigationConflict
    if document is not None:
        obj.document = document.model_dump(mode="json")
    obj.deleted = deleted
    obj.revision += 1
    obj.save(update_fields=["document", "deleted", "revision", "updated_at"])
    return saved(obj)
