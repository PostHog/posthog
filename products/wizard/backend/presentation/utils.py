"""Presentation-layer helpers for wizard endpoints."""

from rest_framework.request import Request

# Hard cap so a misbehaving CLI / runaway team can't tank the worker by
# requesting a giant page. DRF's pagination is layered on top of this.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


def pagination_window(request: Request) -> tuple[int, int]:
    """Read offset / limit from the request, clamped to safe defaults."""

    def _int(name: str, default: int) -> int:
        raw = request.query_params.get(name)
        if raw is None:
            return default
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return default

    offset = _int("offset", 0)
    limit = min(_int("limit", DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
    return offset, limit
