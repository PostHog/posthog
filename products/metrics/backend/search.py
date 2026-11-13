"""Shared search helpers for the metrics autocomplete endpoints."""


def _escape_like(search: str) -> str:
    return search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ilike_pattern(search: str) -> str:
    """Escape ILIKE metacharacters so a literal '%'/'_' in the search doesn't wildcard."""
    return f"%{_escape_like(search)}%"


def ilike_prefix_pattern(search: str) -> str:
    """An escaped ILIKE pattern that matches names starting with `search`."""
    return f"{_escape_like(search)}%"
