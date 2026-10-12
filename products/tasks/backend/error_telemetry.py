"""Shared shaping of error details for task run failure telemetry."""

ERROR_MESSAGE_TELEMETRY_LIMIT = 500


def truncate_error_message(message: str | None, limit: int = ERROR_MESSAGE_TELEMETRY_LIMIT) -> str:
    """Truncate an error message keeping its tail.

    Agent and wizard failures bury the root cause at the end of their output
    (boilerplate preamble first, actual error last), so head truncation hides it.
    """
    if not message:
        return ""
    return message if len(message) <= limit else message[-limit:]


# Values the agent writes to run state when the failure comes from the user's own account.
_AGENT_REPORTED_FAILURE_CATEGORIES = frozenset(
    {"user_limit", "org_limit", "model_gate", "model_unavailable", "credential_not_delivered"}
)


def task_run_failure_category(error_type: str | None, state: object) -> str:
    """Group a run failure so alerts can leave out failures that one account causes."""
    reported = state.get("failure_category") if isinstance(state, dict) else None
    if reported in _AGENT_REPORTED_FAILURE_CATEGORIES:
        return reported
    if error_type == "SandboxProvisionError":
        return "sandbox_provisioning"
    if error_type == "agent_reported":
        return "agent_error"
    return "platform"
