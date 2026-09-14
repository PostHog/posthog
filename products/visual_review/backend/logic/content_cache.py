"""Content named by its own hash, parsed once and kept in the cache.

A hash names exactly one content, so a cached value can never be stale and nothing has to
invalidate it. The timeout only frees memory for content that nobody reads any more.
"""

from collections.abc import Callable
from typing import TypeVar

from django.core.cache import cache

T = TypeVar("T")

_TIMEOUT_SECONDS = 60 * 60 * 24


def load_by_hash(kind: str, content_hash: str, load: Callable[[], T | None]) -> T | None:
    """The parsed content that a hash names, from the cache or from `load`.

    None is never cached, so content that could not be read this time is read again next time.
    """
    key = f"visual_review:{kind}:{content_hash}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    value = load()
    if value is not None:
        cache.set(key, value, timeout=_TIMEOUT_SECONDS)
    return value
