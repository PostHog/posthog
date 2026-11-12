import re
import difflib
from collections.abc import Iterable

_SEPARATORS = re.compile(r"[\s_\-]+")


def _normalize(name: str) -> str:
    return _SEPARATORS.sub("", name).lower()


def resolve_source_type(name: str, candidates: Iterable[str]) -> str | None:
    """Return the canonical key for `name`, ignoring case, spaces, hyphens and underscores.

    An exact match wins. A normalized match that fits more than one key is ambiguous, so it returns None.
    """
    keys = list(candidates)
    if name in keys:
        return name
    normalized = _normalize(name)
    if not normalized:
        return None
    matches = [key for key in keys if _normalize(key) == normalized]
    return matches[0] if len(matches) == 1 else None


def suggest_source_types(name: str, candidates: Iterable[str], limit: int = 3) -> list[str]:
    """Return up to `limit` canonical keys that look like `name`, best match first."""
    by_normalized: dict[str, str] = {}
    for key in candidates:
        by_normalized.setdefault(_normalize(key), key)
    close = difflib.get_close_matches(_normalize(name), list(by_normalized), n=limit, cutoff=0.7)
    return [by_normalized[match] for match in close]
