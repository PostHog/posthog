"""Surface the underlying cause of Temporal-wrapped failures for telemetry."""

import temporalio.exceptions

# Cap the message so a stack-trace-laden error can't bloat the analytics event.
MAX_ERROR_MESSAGE_LENGTH = 300


def describe_exception(exc: BaseException) -> tuple[str, str]:
    """Return ``(error_type, error_message)`` for the most specific cause of ``exc``.

    Activity failures reach a workflow as an ``ActivityError`` wrapping an ``ApplicationError``
    whose ``type`` carries the original exception's class name, so a flat ``str(exc)`` loses the
    real downstream error. Walk the cause chain to the deepest link, preferring an
    ``ApplicationError.type`` (and a concrete non-wrapper exception's class) over the generic
    Temporal wrappers.
    """
    error_type = type(exc).__name__
    message = str(exc)
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, temporalio.exceptions.ApplicationError):
            error_type = current.type or type(current).__name__
            message = current.message or message
        elif not isinstance(current, temporalio.exceptions.FailureError):
            # A concrete (non-wrapper) exception — the most specific type available.
            error_type = type(current).__name__
            message = str(current)
        # FailureError subclasses (ActivityError, ChildWorkflowError, …) are pure wrappers:
        # keep unwrapping without overwriting the more specific info found so far.
        current = getattr(current, "cause", None) or current.__cause__
    return error_type, message[:MAX_ERROR_MESSAGE_LENGTH]
