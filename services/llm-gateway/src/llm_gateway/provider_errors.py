# litellm's RateLimitError replaces the provider's own code with the status `429` and its own type
# `throttling_error`, then rebuilds the response without the upstream body. A code the gateway can
# group on, for example `rate_limit_exceeded`, then survives only on the provider exception that
# litellm was handling.
_LITELLM_RATE_LIMIT_PLACEHOLDERS = frozenset({"429", "throttling_error"})


def provider_error_code(error: Exception) -> str | None:
    """Read the provider's own error code, for example `invalid_organization`.

    litellm copies the code onto the exception for some provider failures and
    leaves it on the response payload for the rest, so both are read.
    """
    code = _own_error_code(error)
    if code not in _LITELLM_RATE_LIMIT_PLACEHOLDERS:
        return code
    return _handled_error_code(error) or code


def _own_error_code(error: BaseException) -> str | None:
    direct = getattr(error, "code", None) or getattr(error, "type", None)
    if direct:
        return str(direct)

    payload = getattr(error, "body", None) or _read_json(getattr(error, "response", None))
    return error_code_from_payload(payload)


def _handled_error_code(error: BaseException) -> str | None:
    """Read the code from the provider exception that litellm was handling.

    litellm maps and raises inside an `except` block, so Python puts the provider exception on
    `__context__`. The two statuses must match, which keeps an unrelated exception that happened
    to be in flight out of the result.
    """
    status = getattr(error, "status_code", None)
    original = error.__context__
    if original is None or status is None or getattr(original, "status_code", None) != status:
        return None
    return _own_error_code(original)


def error_code_from_payload(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    fields = error if isinstance(error, dict) else payload
    code = fields.get("code") or fields.get("type")
    return str(code) if code else None


def _read_json(response: object) -> object:
    reader = getattr(response, "json", None)
    if not callable(reader):
        return None
    try:
        return reader()
    except Exception:
        # An error code is not worth an exception, and litellm builds placeholder
        # responses that carry no body at all.
        return None
