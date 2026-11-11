"""The record that ties an imported Customer.io automation to its draft workflow."""

from dataclasses import asdict
from uuid import UUID

from posthog.models import Team, User

from products.workflows.backend.facade.contracts import ImportNote, PreviousImport, WorkflowImportRecord
from products.workflows.backend.facade.enums import HogFlowState, WorkflowImportSource
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.workflow_import import WorkflowImport


def previous_import(team: Team, source_id: str) -> PreviousImport:
    record = (
        WorkflowImport.objects.for_team(team.id)
        .filter(source=WorkflowImportSource.CUSTOMERIO.value, source_id=source_id)
        .first()
    )
    flow = (
        HogFlow.objects.filter(team_id=team.id, pk=record.hog_flow_id).only("id", "status", "created_by_id").first()
        if record is not None and record.hog_flow_id
        else None
    )
    return PreviousImport(
        record_id=record.id if record else None,
        hog_flow_id=flow.id if flow else None,
        hog_flow_is_draft=flow is not None and flow.status == HogFlowState.DRAFT.value,
        hog_flow_created_by_id=flow.created_by_id if flow else None,
    )


def record_import(
    *,
    team: Team,
    user: User,
    record_id: UUID | None,
    source_id: str,
    name: str,
    hog_flow_id: UUID,
    notes: tuple[ImportNote, ...],
) -> None:
    stored_notes = [{**asdict(note), "level": note.level.value} for note in notes]
    if record_id is None:
        WorkflowImport.objects.create(
            team=team,
            source=WorkflowImportSource.CUSTOMERIO.value,
            source_id=source_id,
            source_name=name[:400],
            hog_flow_id=hog_flow_id,
            notes=stored_notes,
            created_by=user,
        )
        return
    record = WorkflowImport.objects.for_team(team.id).get(pk=record_id)
    record.hog_flow_id = hog_flow_id
    record.source_name = name[:400]
    record.notes = stored_notes
    record.save(update_fields=["hog_flow", "source_name", "notes", "updated_at"])


def import_for_workflow(team: Team, hog_flow_id: UUID) -> WorkflowImportRecord | None:
    record = WorkflowImport.objects.for_team(team.id).filter(hog_flow_id=hog_flow_id).order_by("-updated_at").first()
    if record is None:
        return None
    flow = HogFlow.objects.filter(team_id=team.id, pk=hog_flow_id).only("id", "created_by_id").first()
    return WorkflowImportRecord(
        id=record.id,
        source=record.source,
        source_id=record.source_id,
        source_name=record.source_name,
        hog_flow_id=record.hog_flow_id,
        notes=tuple(record.notes or []),
        updated_at=record.updated_at,
        hog_flow_created_by_id=flow.created_by_id if flow else None,
    )
