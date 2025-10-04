from typing import Optional


class ProcessTaskError(Exception):
    def __init__(self, message: str, context: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            return f"{self.message} (context: {self.context})"
        return self.message


class ProcessTaskFatalError(ProcessTaskError):
    """Fatal errors that should not be retried."""

    pass


class ProcessTaskTransientError(ProcessTaskError):
    """Transient errors that may succeed on retry."""

    pass


class TaskNotFoundError(ProcessTaskFatalError):
    pass


class TaskInvalidStateError(ProcessTaskFatalError):
    pass


class SandboxProvisionError(ProcessTaskTransientError):
    """Failed to provision sandbox environment."""

    pass


class SandboxExecutionError(ProcessTaskError):
    """Error during sandbox command execution."""

    pass


class SandboxTimeoutError(ProcessTaskError):
    """Sandbox operation timed out."""

    pass


class SnapshotNotFoundError(ProcessTaskTransientError):
    """Snapshot does not exist or is not ready."""

    pass


class SnapshotCreationError(ProcessTaskTransientError):
    """Failed to create snapshot."""

    pass


class RepositoryCloneError(ProcessTaskTransientError):
    """Failed to clone repository."""

    pass


class RepositorySetupError(ProcessTaskTransientError):
    """Failed to setup repository (install dependencies, etc)."""

    pass


class GitHubIntegrationError(ProcessTaskFatalError):
    """GitHub integration not found or invalid."""

    pass


class GitHubAuthenticationError(ProcessTaskFatalError):
    """Failed to authenticate with GitHub."""

    pass


class PersonalAPIKeyError(ProcessTaskTransientError):
    """Failed to create or inject personal API key."""

    pass


class TaskExecutionFailedError(ProcessTaskError):
    """Task execution completed but with non-zero exit code."""

    def __init__(
        self, message: str, exit_code: int, stdout: str = "", stderr: str = "", context: Optional[dict] = None
    ):
        super().__init__(message, context)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
