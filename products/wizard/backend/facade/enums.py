"""
Exported enums for wizard.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic.py, models.py).
"""

from enum import StrEnum


class WizardSessionRunPhase(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class WizardSessionTaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

    # These are not currently used, but we want to reserve them for future use.
    FAILED = "failed"
    CANCELED = "canceled"


RunPhase = WizardSessionRunPhase
TaskStatus = WizardSessionTaskStatus


class WizardRunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WizardRunDispatchStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"


class WizardRunStage(StrEnum):
    DISPATCHING = "dispatching"
    PROVISIONING = "provisioning"
    PREPARING_WORKSPACE = "preparing_workspace"
    EXECUTING_WIZARD = "executing_wizard"
    CREATING_ARTIFACTS = "creating_artifacts"


class WizardWorkerCleanupStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    CLEANED = "cleaned"
    FAILED = "failed"


class WizardRunEnvironment(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"


class WizardWorkspaceType(StrEnum):
    LOCAL_FOLDER = "local_folder"
    GIT_REPOSITORY = "git_repository"


class WizardRunErrorCode(StrEnum):
    TIMEOUT = "timeout"
    PROVISIONING_FAILED = "provisioning_failed"
    REPOSITORY_ACCESS_FAILED = "repository_access_failed"
    WORKSPACE_PREPARATION_FAILED = "workspace_preparation_failed"
    EXECUTION_FAILED = "execution_failed"
    ARTIFACT_CREATION_FAILED = "artifact_creation_failed"
    DISPATCH_FAILED = "dispatch_failed"


class WizardRunArtifactType(StrEnum):
    GIT_DIFF = "git_diff"
    PULL_REQUEST = "pull_request"
