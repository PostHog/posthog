"""Shared shaping of error details for task run failure telemetry."""

ERROR_MESSAGE_TELEMETRY_LIMIT = 500

# Dedicated failure reason for a run that exhausted its per-run gateway spend cap.
# A capped run dies mid-turn with an HTTP 402 "admission rejected" from the gateway;
# mapping it to a stable reason here is the single place any surface matches that
# wording, so cap-hit counting survives error-message changes.
SPEND_CAPPED_ERROR_TYPE = "spend_capped"

# Signatures the gateway returns when a run's scoped-token cap is exhausted. Matched
# case-insensitively against the failure message. Kept narrow so an unrelated 402
# never reads as a cap hit.
_SPEND_CAP_SIGNATURES = ("admission rejected", "token_cap_exceeded")


def truncate_error_message(message: str | None, limit: int = ERROR_MESSAGE_TELEMETRY_LIMIT) -> str:
    """Truncate an error message keeping its tail.

    Agent and wizard failures bury the root cause at the end of their output
    (boilerplate preamble first, actual error last), so head truncation hides it.
    """
    if not message:
        return ""
    return message if len(message) <= limit else message[-limit:]


def is_spend_cap_failure(message: str | None) -> bool:
    """Whether a failure message is a per-run gateway spend-cap exhaustion."""
    if not message:
        return False
    lowered = message.lower()
    return any(signature in lowered for signature in _SPEND_CAP_SIGNATURES)
