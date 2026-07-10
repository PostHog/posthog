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
