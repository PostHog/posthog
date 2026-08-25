"""Shared non-retryable-error helpers for warehouse sources.

`get_non_retryable_errors()` returns a dict mapping a substring of the stringified exception to a
friendly message; the pipeline fails the job (instead of retrying) when a raised error contains one
of these substrings. Nearly every source hand-writes the same 401/403 pair, so centralize it here.
"""


def auth_non_retryable_errors(host: str | None = None, *, service: str | None = None) -> dict[str, str | None]:
    """Standard 401/403 -> friendly-message map for `get_non_retryable_errors()`.

    A bad or unscoped credential is permanent, not transient, so the job should fail fast rather than
    retry. Keys match the stable ``requests`` ``raise_for_status()`` text as a substring.

    Pass ``host`` (the source's base URL) to scope the match to this source's requests — e.g.
    ``"401 Client Error: Unauthorized for url: https://api.example.com"`` — so an unrelated 401 from a
    different host in the same job can't match. Omit it for a host-agnostic match. ``service`` names
    the vendor in the message. Sources with provider-specific copy should still hand-write their own.
    """
    svc = f"{service} " if service else ""
    unauthorized = f"Your {svc}API key or token is invalid or expired. Please reconnect with valid credentials."
    forbidden = (
        f"Your {svc}credentials don't have permission to access this resource. Check the key's scopes and reconnect."
    )
    if host:
        return {
            f"401 Client Error: Unauthorized for url: {host}": unauthorized,
            f"403 Client Error: Forbidden for url: {host}": forbidden,
        }
    return {"401 Client Error": unauthorized, "403 Client Error": forbidden}


# Host-agnostic default, for sources that just want the common pair with no service name.
AUTH_401_403_ERRORS: dict[str, str | None] = auth_non_retryable_errors()
