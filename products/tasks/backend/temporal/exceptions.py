from typing import Any, Optional

from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception


class ProcessTaskError(ApplicationError):
    def __init__(self, message: str, context: dict[str, Any], cause: Exception, **kwargs):
        self.context = context or {}
        if "team" not in self.context:
            self.context["team"] = "array"

        if cause is not None:
            capture_exception(cause, self.context)

        super().__init__(message, self.context, **kwargs)


class ProcessTaskFatalError(ProcessTaskError):
    """Fatal errors that should not be retried."""

    def __init__(self, message: str, context: dict[str, Any], cause: Exception, **kwargs):
        super().__init__(message, context, cause, non_retryable=True, **kwargs)


class ProcessTaskTransientError(ProcessTaskError):
    """Transient errors that may succeed on retry."""

    def __init__(self, message: str, context: dict[str, Any], cause: Exception, **kwargs):
        super().__init__(message, context, cause, non_retryable=False, **kwargs)


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


class RetryableRepositorySetupError(ProcessTaskTransientError):
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


class OAuthTokenError(ProcessTaskTransientError):
    """Failed to create OAuth access token."""

    pass


class TaskExecutionFailedError(ProcessTaskError):
    """Task execution completed but with non-zero exit code."""

    def __init__(
        self,
        message: str,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
        context: Optional[dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        non_retryable: bool = False,
    ):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        if cause is None:
            cause = RuntimeError(f"Task failed with exit code {exit_code}")
        super().__init__(message, context or {}, cause, non_retryable=non_retryable)
