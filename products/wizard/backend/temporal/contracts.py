from uuid import UUID

from posthog.dataclasses import frozen

from products.wizard.backend.facade.enums import WizardRunStatus, WizardWorkspaceType


@frozen
class WizardRunActivityInput:
    team_id: int
    run_id: UUID
    use_local_wizard_source: bool = False


@frozen
class WizardRunFinalizationActivityInput:
    team_id: int
    run_id: UUID
    status: WizardRunStatus
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status not in (WizardRunStatus.FAILED, WizardRunStatus.CANCELLED):
            raise ValueError("Wizard Run finalization requires a failed or cancelled status.")
        if self.status != WizardRunStatus.FAILED and self.error_code is not None:
            raise ValueError("Only failed Wizard Runs can have an error code.")


@frozen
class ProvisionedWizardWorker:
    team_id: int
    run_id: UUID
    sandbox_id: str
    workspace_type: WizardWorkspaceType
    use_local_wizard_source: bool = False


@frozen
class PreparedGitRepositoryWorkspace:
    team_id: int
    run_id: UUID
    sandbox_id: str
    repository: str
    root_path: str
    github_integration_id: int
    use_local_wizard_source: bool = False
