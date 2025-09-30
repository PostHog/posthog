from dataclasses import dataclass


@dataclass
class GetBaseSnapshotInput:
    github_integration_id: int
    team_id: int


@dataclass
class GetBaseSnapshotOutput:
    snapshot_id: str
    external_id: str
    repos: list[str]
    status: str
    is_new: bool


@dataclass
class CheckSnapshotExistsForRepositoryInput:
    github_integration_id: int
    repository: str


@dataclass
class CheckSnapshotExistsForRepositoryOutput:
    exists: bool
    snapshot_id: str | None


@dataclass
class SetupRepoInSnapshotInput:
    github_integration_id: int
    team_id: int
    repository: str


@dataclass
class SetupRepoInSnapshotOutput:
    success: bool
    new_external_id: str
    setup_logs: str
    error: str | None = None


@dataclass
class CreateSandboxInput:
    sandbox_name: str
    snapshot_external_id: str
    github_integration_id: int
    team_id: int
    task_id: str


@dataclass
class CreateSandboxOutput:
    sandbox_id: str
    status: str
    working_directory: str


@dataclass
class GetGitHubTokenInput:
    sandbox_id: str
    github_integration_id: int
    team_id: int


@dataclass
class GetGitHubTokenOutput:
    success: bool
    expires_at: str


@dataclass
class CreateTemporaryAPIKeyInput:
    sandbox_id: str
    user_id: int
    team_id: int
    task_id: str


@dataclass
class CreateTemporaryAPIKeyOutput:
    api_key_id: str
    success: bool


@dataclass
class ExecuteCodeAgentInput:
    sandbox_id: str
    task_id: str
    repository: str


@dataclass
class ExecuteCodeAgentOutput:
    success: bool
    execution_id: str
    execution_logs: str
    files_changed: list[str]
    exit_code: int
    duration_seconds: float


@dataclass
class CleanupSandboxInput:
    sandbox_id: str


@dataclass
class CleanupSandboxOutput:
    success: bool


@dataclass
class TaskDetails:
    task_id: str
    team_id: int
    user_id: int
    github_integration_id: int
    repository: str


@dataclass
class CreateSandboxForSetupInput:
    base_snapshot_external_id: str


@dataclass
class CloneRepositoryInput:
    sandbox_id: str
    repository: str
    github_integration_id: int


@dataclass
class SetupRepositoryInput:
    sandbox_id: str
    repository: str


@dataclass
class InitiateSnapshotInput:
    sandbox_id: str


@dataclass
class PollSnapshotStatusInput:
    snapshot_external_id: str


@dataclass
class FinalizeSnapshotRecordInput:
    snapshot_record_id: str
    snapshot_external_id: str


@dataclass
class MarkSnapshotErrorInput:
    snapshot_record_id: str


@dataclass
class CreateSandboxFromSnapshotInput:
    snapshot_id: str


@dataclass
class ExecuteTaskInput:
    sandbox_id: str
    task_id: str
    repository: str
