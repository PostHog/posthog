"""Shared search helpers for the metrics autocomplete endpoints."""


def ilike_pattern(search: str) -> str:
    """Escape ILIKE metacharacters so a literal '%'/'_' in the search doesn't wildcard."""
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
