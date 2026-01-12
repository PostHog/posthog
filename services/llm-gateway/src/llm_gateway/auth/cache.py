import time
from dataclasses import dataclass
from datetime import UTC, datetime

from cachetools import LRUCache

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings


@dataclass(slots=True)
class CachedAuthEntry:
    user: AuthenticatedUser | None
    expires_at: float


class AuthCache:
    def __init__(self, max_size: int | None = None, ttl: int | None = None) -> None:
        settings = get_settings()
        self._max_size = max_size if max_size is not None else settings.auth_cache_max_size
        self._ttl = ttl if ttl is not None else settings.auth_cache_ttl
        self._cache: LRUCache[str, CachedAuthEntry] = LRUCache(maxsize=self._max_size)

    def get(self, key: str) -> tuple[bool, AuthenticatedUser | None]:
        entry = self._cache.get(key)
        if entry is None:
            return False, None

        if time.monotonic() > entry.expires_at:
            self._cache.pop(key, None)
            return False, None

        user = entry.user
        if user and user.token_expires_at and user.token_expires_at < datetime.now(UTC):
            self._cache.pop(key, None)
            return False, None

        return True, user

    def set(self, key: str, user: AuthenticatedUser | None) -> None:
        expires_at = time.monotonic() + self._ttl
        self._cache[key] = CachedAuthEntry(user=user, expires_at=expires_at)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        """Current number of entries in the cache."""
        return len(self._cache)


_auth_cache: AuthCache | None = None


def get_auth_cache() -> AuthCache:
    """Get the singleton auth cache instance."""
    global _auth_cache
    if _auth_cache is None:
        _auth_cache = AuthCache()
    return _auth_cache


def reset_auth_cache() -> None:
    """Reset the auth cache (for testing)."""
    global _auth_cache
    _auth_cache = None
