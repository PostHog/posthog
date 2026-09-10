from datetime import timedelta
from typing import Any, Optional

from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception

from products.tasks.backend.facade.compute_quota import ComputeBillingLimitExceeded


class ProcessTaskError(ApplicationError):
    def __init__(
        self, message: str, context: dict[str, Any], cause: Optional[BaseException], capture: bool = True, **kwargs
    ):
        self.context = context or {}
        if "team" not in self.context:
            self.context["team"] = "array"

        # `capture=False` skips error-tracking capture for expected, recoverable failures
        # (e.g. transient infra timeouts that Temporal retries) so they don't create noisy issues.
        if cause is not None and capture:
            capture_exception(cause, self.context)

        # Retry policies match non_retryable_error_types against this type; the SDK omits it unless set.
        kwargs.setdefault("type", type(self).__name__)
        super().__init__(message, self.context, **kwargs)


class ProcessTaskFatalError(ProcessTaskError):
    """Fatal errors that should not be retried."""

    def __init__(self, message: str, context: dict[str, Any], cause: Exception, **kwargs):
        super().__init__(message, context, cause, non_retryable=True, **kwargs)


class ProcessTaskTransientError(ProcessTaskError):
    """Transient errors that may succeed on retry."""

    def __init__(self, message: str, context: dict[str, Any], cause: BaseException, **kwargs):
        super().__init__(message, context, cause, non_retryable=False, **kwargs)


class TaskNotFoundError(ProcessTaskFatalError):
    pass


class TaskRunNotReadyError(ProcessTaskTransientError):
    """The TaskRun row is not yet visible to this activity.

    Typically the creating transaction has not committed by the time the activity's
    first read runs (the run was created inside an enclosing transaction.atomic block).
    Retryable so the activity's existing retry policy recovers once the row is visible.
    Intentionally does not capture to error tracking — this is an expected transient
    window the retry absorbs, not a fault worth an issue.
    """

    def __init__(self, message: str, context: dict[str, Any]):
        # Bypass ProcessTaskTransientError.__init__ to pass cause=None, which skips the
        # capture_exception() call in ProcessTaskError — avoiding error-tracking noise.
        ProcessTaskError.__init__(self, message, context, None, non_retryable=False)


class GitHubRateLimitedError(ProcessTaskTransientError):
    """GitHub rate-limited a call (or our egress budget shed it before it was sent).

    An expected, recoverable condition rather than a fault. Kept retryable so the
    activity's retry policy recovers once the limit window passes, but intentionally
    not captured to error tracking — there is nothing to investigate, and capturing
    it mints a noisy issue for something we expect to happen. ``retry_after`` (seconds)
    drives ``next_retry_delay`` so the retry lands after the window instead of burning
    every attempt inside it, and is folded into the message so the surfaced error names
    a real wait instead of an empty reset time.
    """

    def __init__(self, message: str, context: dict[str, Any], retry_after: int):
        # Bypass ProcessTaskTransientError.__init__ to pass cause=None with capture=False,
        # skipping the capture_exception() call in ProcessTaskError (mirrors TaskRunNotReadyError).
        ProcessTaskError.__init__(
            self,
            message,
            context,
            None,
            capture=False,
            non_retryable=False,
            next_retry_delay=timedelta(seconds=retry_after),
        )


class TaskInvalidStateError(ProcessTaskFatalError):
    pass


class SandboxProvisionError(ProcessTaskTransientError):
    """Failed to provision sandbox environment."""

    pass


class ComputeBillingLimitError(ProcessTaskError, ComputeBillingLimitExceeded):
    def __init__(self, context: dict[str, Any], reason: str = "posthog_code_billing_limit_exceeded"):
        from products.tasks.backend.logic.services.compute_quota import ORGANIZATION_DEACTIVATED_DENIAL_CODE

        self.reason = reason
        message = (
            "Your organization has been deactivated."
            if reason == ORGANIZATION_DEACTIVATED_DENIAL_CODE
            else "Your organization reached its PostHog Desktop usage limit."
        )
        super().__init__(
            message,
            {**context, "reason": reason},
            None,
            capture=False,
            non_retryable=True,
        )


class SandboxNetworkPolicyError(ProcessTaskFatalError):
    pass


class SandboxNotFoundError(ProcessTaskFatalError):
    """Sandbox does not exist."""

    pass


class SandboxExecutionError(ProcessTaskTransientError):
    """Error during sandbox command execution."""

    pass


class SandboxMissingRepositoryError(ProcessTaskFatalError):
    """The repository directory the agent-server needs as its cwd is absent from the sandbox.

    Happens when a run reaches agent-server start without a clone — no snapshot restored and no
    usable GitHub credentials. Retrying cannot make the directory appear, so fail immediately
    with the real reason instead of burning health-check timeouts on a server that can never
    open a session.
    """

    pass


class SandboxNotRunningError(SandboxExecutionError):
    """Sandbox is not in a running state."""

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


class SnapshotTimeoutError(ProcessTaskTransientError):
    """Transient timeout/connection error while creating a snapshot; safe to retry."""

    pass


class SnapshotFileLimitExceededError(ProcessTaskFatalError):
    """Modal refuses to snapshot a directory/filesystem holding more than its hard file-count
    cap (1,000,000 files). This is a permanent limit, not a transient blip, so retrying the same
    snapshot cannot succeed — the caller must shrink the tree (prune node_modules, virtualenvs,
    and package caches) before it can snapshot.

    Non-retryable and captured to error tracking: it is a named, classified condition (not the
    generic mystery issue this replaced), and callers with no fallback — the dev-stack image bake,
    the standalone snapshot activity — need it visible. The resume path recovers by pruning and
    letting Temporal retry, so it converts this into a transient error itself rather than swallowing
    the signal.
    """

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


class CredentialUnavailableError(ProcessTaskFatalError):
    """A sandbox credential can never be resolved again for this run — the backing
    integration row was deleted mid-run or the user must re-authorize.

    Not retriable, and an expected customer-initiated state rather than a systemic
    failure, so it is not captured to error tracking.
    """

    def __init__(self, message: str, context: dict[str, Any], cause: Exception | None = None):
        ProcessTaskError.__init__(self, message, context, cause, capture=False, non_retryable=True)


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
