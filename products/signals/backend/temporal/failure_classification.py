"""Classify a caught report-generation exception into a specific ``failure_reason``.

The summary workflow and the repo-selection activity both wrap their whole flow in a broad
``except Exception``. Recording every caught error under one catch-all bucket means a spike in the
failure-rate alert can't be told apart from an LLM rate limit, a silent sandbox agent, or a broken
GitHub integration without digging through Temporal history. This maps the common modes to distinct
reasons so the telemetry says what actually broke.

The classifier works both inside an activity (where it sees the raw Python exception) and inside the
workflow (where the same failure arrives as a Temporal ``ActivityError`` wrapping an
``ApplicationError`` or ``TimeoutError``). Anything it can't place stays in the historical catch-all
bucket, so the existing failure-rate series remains continuous.
"""

import temporalio.exceptions
from temporalio.exceptions import ApplicationError

from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.temporal.common.errors import unwrap_temporal_cause

# Kept as the pre-existing catch-all name so the historical failure-rate series stays continuous;
# now only used when no more specific mode matches.
FAILURE_REASON_UNKNOWN = "agentic_activity_error"
FAILURE_REASON_GITHUB_INTEGRATION = "github_integration_error"
FAILURE_REASON_LLM_RATE_LIMIT_OR_TIMEOUT = "llm_rate_limit_or_timeout"
FAILURE_REASON_SANDBOX_AGENT_TIMEOUT = "sandbox_agent_timeout"

# GitHub App auth failures that won't recover on retry (installation gone/suspended). Mirrors the set
# select_repository.py already treats as permanent.
_GITHUB_APP_AUTH_STATUS_CODES = {401, 403, 404, 410}

# Matched case-insensitively against the terminal error text. Once a failure has crossed the Temporal
# activity boundary the provider's own exception type is gone, so the message the sandbox agent
# surfaced (it writes the classified upstream cause into its log) is the only signal left.
_LLM_RATE_LIMIT_OR_TIMEOUT_MARKERS = (
    "rate limit",
    "rate_limit",
    "ratelimit",
    "429",
    "overloaded",
    "too many requests",
    "apitimeout",
    "api timeout",
    "apiconnection",
    "request timed out",
    "read timed out",
    "llm timeout",
)
_SANDBOX_AGENT_TIMEOUT_MARKERS = (
    "poll_for_turn: timed out",
    "inactivity timeout",
    "inactivitytimeout",
    "reached terminal status",
    "no agent message",
    "end_turn with no agent_message",
)


def _leaf_cause(exc: BaseException) -> BaseException:
    """Walk to the innermost Temporal failure (e.g. ActivityError → TimeoutError)."""
    current = exc
    while isinstance(current, temporalio.exceptions.FailureError) and current.cause is not None:
        current = current.cause
    return current


def _error_text(exc: BaseException, application_error: ApplicationError | None) -> str:
    parts: list[str] = []
    if application_error is not None and application_error.message:
        parts.append(application_error.message)
    parts.append(str(exc))
    return " ".join(parts).lower()


def classify_failure_reason(exc: BaseException) -> str:
    """Map a caught pipeline exception to a specific ``failure_reason`` for telemetry."""
    # GitHub App auth failures: the raw exception inside the activity...
    if isinstance(exc, GitHubIntegrationError) and exc.status_code in _GITHUB_APP_AUTH_STATUS_CODES:
        return FAILURE_REASON_GITHUB_INTEGRATION

    application_error = unwrap_temporal_cause(exc)
    if application_error is None and isinstance(exc, ApplicationError):
        application_error = exc
    # ...or the ApplicationError select_repository re-raises it as (type="GitHubIntegrationError"),
    # once it has crossed the activity boundary into the workflow.
    if application_error is not None and application_error.type == "GitHubIntegrationError":
        return FAILURE_REASON_GITHUB_INTEGRATION

    # An LLM rate limit / timeout surfaces as text even when it reached us through the sandbox's
    # terminal-status path, so check it before the sandbox markers — it's the real upstream cause.
    message = _error_text(exc, application_error)
    if any(marker in message for marker in _LLM_RATE_LIMIT_OR_TIMEOUT_MARKERS):
        return FAILURE_REASON_LLM_RATE_LIMIT_OR_TIMEOUT
    if any(marker in message for marker in _SANDBOX_AGENT_TIMEOUT_MARKERS):
        return FAILURE_REASON_SANDBOX_AGENT_TIMEOUT

    # An activity that blows its start_to_close / heartbeat timeout arrives as ActivityError whose
    # leaf cause is a Temporal TimeoutError (not an ApplicationError) — the sandbox agent went silent.
    if isinstance(_leaf_cause(exc), temporalio.exceptions.TimeoutError):
        return FAILURE_REASON_SANDBOX_AGENT_TIMEOUT

    return FAILURE_REASON_UNKNOWN
