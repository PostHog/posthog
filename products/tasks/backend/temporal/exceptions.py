from typing import Optional

from temporalio.exceptions import ApplicationError


class ProcessTaskError(ApplicationError):
    def __init__(self, message: str, context: Optional[dict] = None, **kwargs):
        self.context = context or {}
        super().__init__(message, self.context, **kwargs)


class ProcessTaskFatalError(ProcessTaskError):
    """Fatal errors that should not be retried."""

    def __init__(self, message: str, context: Optional[dict] = None):
        super().__init__(message, context, non_retryable=True)


class ProcessTaskTransientError(ProcessTaskError):
    """Transient errors that may succeed on retry."""

    def __init__(self, message: str, context: Optional[dict] = None):
        super().__init__(message, context, non_retryable=False)


class TaskNotFoundError(ProcessTaskFatalError):
    pass


class TaskInvalidStateError(ProcessTaskFatalError):
    pass


class SandboxProvisionError(ProcessTaskTransientError):
    """Failed to provision sandbox environment."""

    pass


class SandboxNotFoundError(ProcessTaskFatalError):
    """Sandbox does not exist."""

    pass


class SandboxExecutionError(ProcessTaskTransientError):
    """Error during sandbox command execution."""

    pass


class SandboxTimeoutError(ProcessTaskTransientError):
    """Sandbox operation timed out."""

    pass


class SandboxCleanupError(ProcessTaskTransientError):
    """Error during sandbox cleanup/destruction."""

    pass


class SnapshotNotFoundError(ProcessTaskTransientError):
    """Snapshot does not exist."""

    pass


class SnapshotNotReadyError(ProcessTaskTransientError):
    """Snapshot exists but is not ready for use."""

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
        self,
        message: str,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
        context: Optional[dict] = None,
        non_retryable: bool = False,
    ):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(message, context, non_retryable=non_retryable)
