def provider_error_code(error: Exception) -> str | None:
    """Read the provider's own error code, for example `invalid_organization`.

    litellm copies the code onto the exception for some provider failures and
    leaves it on the response payload for the rest, so both are read.
    """
    direct = getattr(error, "code", None) or getattr(error, "type", None)
    if direct:
        return str(direct)

    payload = getattr(error, "body", None) or _read_json(getattr(error, "response", None))
    return error_code_from_payload(payload)


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
