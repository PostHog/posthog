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
class CheckRepoInSnapshotInput:
    github_integration_id: int
    repository: str


@dataclass
class CheckRepoInSnapshotOutput:
    exists: bool
    snapshot_id: str | None


@dataclass
class SetupRepoInSnapshotInput:
    github_integration_id: int
    team_id: int
    repository: str
    github_token: str


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
    api_key_id: str | None = None
    kill_execution_id: str | None = None


@dataclass
class CleanupSandboxOutput:
    success: bool
