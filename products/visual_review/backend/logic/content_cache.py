"""Content named by its own hash, parsed once and kept in the cache.

A hash names exactly one content, so a cached value can never be stale and nothing has to
invalidate it. The timeout only frees memory for content that nobody reads any more. The cache is
only an optimization, so a cache that cannot be reached counts as a miss and the content is read
from its source.
"""

from collections.abc import Callable
from typing import TypeVar

from posthog.utils import get_safe_cache, safe_cache_set

T = TypeVar("T")

# Short, because entries live in the shared cache. CI runs read the same blob many times within an
# hour, so a short entry keeps almost every hit.
_TIMEOUT_SECONDS = 60 * 60


def load_by_hash(kind: str, content_hash: str, load: Callable[[], T | None]) -> T | None:
    """The parsed content that a hash names, from the cache or from `load`.

    None is never cached, so content that could not be read this time is read again next time.
    """
    key = f"visual_review:{kind}:{content_hash}"
    cached = get_safe_cache(key)
    if cached is not None:
        return cached
    value = load()
    if value is not None:
        safe_cache_set(key, value, timeout=_TIMEOUT_SECONDS)
    return value
