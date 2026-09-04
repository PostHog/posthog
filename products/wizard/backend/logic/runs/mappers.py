from products.wizard.backend.facade.contracts import (
    GitRepositoryWorkspace,
    LocalFolderWorkspace,
    WizardRunDTO,
    WizardWorkspace,
)
from products.wizard.backend.facade.enums import (
    WizardRunEnvironment,
    WizardRunStage,
    WizardRunStatus,
    WizardWorkspaceType,
)
from products.wizard.backend.facade.validation import validate_workspace_metadata_value
from products.wizard.backend.logic.programs import program_from_mapping
from products.wizard.backend.models import WizardRun


def workspace_to_record(workspace: WizardWorkspace) -> tuple[WizardWorkspaceType, dict[str, object]]:
    match workspace:
        case LocalFolderWorkspace(project_name=project_name):
            return WizardWorkspaceType.LOCAL_FOLDER, {"project_name": project_name}
        case GitRepositoryWorkspace(repository=repository):
            return WizardWorkspaceType.GIT_REPOSITORY, {"repository": repository}


def workspace_from_record(workspace_type: str, metadata: object) -> WizardWorkspace:
    match WizardWorkspaceType(workspace_type):
        case WizardWorkspaceType.LOCAL_FOLDER:
            return LocalFolderWorkspace(project_name=validate_workspace_metadata_value(metadata, "project_name"))
        case WizardWorkspaceType.GIT_REPOSITORY:
            return GitRepositoryWorkspace(repository=validate_workspace_metadata_value(metadata, "repository"))


def run_from_record(run: WizardRun) -> WizardRunDTO:
    return WizardRunDTO(
        id=run.id,
        team_id=run.team_id,
        created_by_id=run.created_by_id,
        environment=WizardRunEnvironment(run.environment),
        workspace=workspace_from_record(run.workspace_type, run.workspace),
        program=program_from_mapping(run.program, allow_latest_version=True),
        status=WizardRunStatus(run.status),
        error_code=run.error_code,
        error_message=run.error_message,
        stage=WizardRunStage(run.stage) if run.stage else None,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        deadline_at=run.deadline_at,
    )
