"""The record that ties an imported Customer.io automation to its draft workflow."""

from dataclasses import asdict
from uuid import UUID

from posthog.models import Team, User

from products.workflows.backend.facade.enums import HogFlowState, WorkflowImportSource
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.workflow_import import WorkflowImport
from products.workflows.backend.services.customerio_import.report import ImportNote


def previous_draft(team: Team, source_id: str) -> tuple[WorkflowImport | None, HogFlow | None]:
    """The earlier import of this automation and its workflow, if both still exist."""
    record = (
        WorkflowImport.objects.for_team(team.id)
        .filter(source=WorkflowImportSource.CUSTOMERIO.value, source_id=source_id)
        .first()
    )
    if record is None or record.hog_flow_id is None:
        return record, None
    return record, HogFlow.objects.filter(team_id=team.id, pk=record.hog_flow_id).first()


def is_draft(flow: HogFlow) -> bool:
    return flow.status == HogFlowState.DRAFT.value


def record_import(
    *,
    team: Team,
    user: User,
    record: WorkflowImport | None,
    source_id: str,
    name: str,
    hog_flow_id: UUID,
    notes: tuple[ImportNote, ...],
) -> None:
    stored_notes = [{**asdict(note), "level": note.level.value} for note in notes]
    if record is None:
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
    record.hog_flow_id = hog_flow_id
    record.source_name = name[:400]
    record.notes = stored_notes
    record.save(update_fields=["hog_flow", "source_name", "notes", "updated_at"])


def import_for_workflow(team: Team, hog_flow_id: UUID) -> WorkflowImport | None:
    return WorkflowImport.objects.for_team(team.id).filter(hog_flow_id=hog_flow_id).order_by("-updated_at").first()
