from posthog.paging import Page, PageRequest

from products.workflows.backend.facade.contracts import WorkflowViewRecord, WorkflowViewState
from products.workflows.backend.services.workflow_views import WorkflowViewStore


def list_workflow_views(team_id: int, page: PageRequest) -> Page[WorkflowViewRecord]:
    return WorkflowViewStore(team_id).list(page)


def get_workflow_view(team_id: int, view_id: str) -> WorkflowViewRecord:
    return WorkflowViewStore(team_id).get(view_id)


def create_workflow_view(team_id: int, *, name: str, state: WorkflowViewState) -> WorkflowViewRecord:
    return WorkflowViewStore(team_id).create(name=name, state=state)


def update_workflow_view(
    team_id: int, view_id: str, version: int, *, name: str | None, state: WorkflowViewState | None
) -> WorkflowViewRecord:
    return WorkflowViewStore(team_id).update(view_id, version, name=name, state=state)


def delete_workflow_view(team_id: int, view_id: str, version: int) -> None:
    WorkflowViewStore(team_id).delete(view_id, version)


def initialize_workflow_views(team_id: int) -> WorkflowViewRecord:
    return WorkflowViewStore(team_id).initialize()


def restore_default_workflow_view(team_id: int) -> WorkflowViewRecord:
    return WorkflowViewStore(team_id).restore_default()
