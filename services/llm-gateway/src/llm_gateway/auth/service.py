import re
from functools import lru_cache

import asyncpg
from fastapi import Request

from llm_gateway.auth.authenticators import Authenticator, OAuthAccessTokenAuthenticator, PersonalApiKeyAuthenticator
from llm_gateway.auth.cache import AuthCache, get_auth_cache
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.metrics.prometheus import AUTH_CACHE_HITS, AUTH_CACHE_MISSES, AUTH_INVALID

BEARER_PATTERN = re.compile(r"^Bearer\s+(\S+)$", re.IGNORECASE)


def extract_token(request: Request) -> str | None:
    """Extract authentication token from request headers."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key.strip()

    auth_header = request.headers.get("authorization")
    if not auth_header:
        return None
    match = BEARER_PATTERN.match(auth_header)
    return match.group(1).strip() if match else None


def upstream_auth_header(request: Request) -> str:
    """Build the Authorization header to forward to PostHog for the request's token.

    Mirrors :func:`extract_token`'s precedence (x-api-key wins over
    Authorization). Auth accepts either header, so any upstream check that
    forwarded only Authorization could be bypassed by sending the same token
    via x-api-key — e.g. plan resolution returning no plan (and with it any
    plan-conditioned enforcement), or quota resolution failing open.
    Returns "" when the request carries no token.
    """
    api_key = request.headers.get("x-api-key")
    if api_key:
        # Not a route handler: this builds an outbound header value from the
        # caller's own credential; nothing is rendered to a response body.
        # nosemgrep: python.flask.security.audit.directly-returned-format-string.directly-returned-format-string
        return f"Bearer {api_key.strip()}"
    return request.headers.get("authorization", "")


class AuthService:
    """Coordinates authentication with caching and metrics."""

    def __init__(self, authenticators: list[Authenticator], cache: AuthCache) -> None:
        self._authenticators = authenticators
        self._cache = cache

    async def authenticate(self, token: str, pool: asyncpg.Pool) -> AuthenticatedUser | None:
        """Authenticate a token, using cache when available."""
        for auth in self._authenticators:
            if not auth.matches(token):
                continue

            token_hash = auth.hash_token(token)

            hit, user = self._cache.get(token_hash)
            if hit:
                AUTH_CACHE_HITS.labels(auth_type=auth.auth_type).inc()
                if user is None:
                    AUTH_INVALID.labels(auth_type=auth.auth_type).inc()
                return user

            AUTH_CACHE_MISSES.labels(auth_type=auth.auth_type).inc()

            user = await auth.authenticate(token_hash, pool)
            self._cache.set(token_hash, user, ttl=auth.cache_ttl)

            if user is None:
                AUTH_INVALID.labels(auth_type=auth.auth_type).inc()

            return user

        return None

    async def authenticate_request(self, request: Request, pool: asyncpg.Pool) -> AuthenticatedUser | None:
        """Extract token from request and authenticate."""
        token = extract_token(request)
        if not token:
            return None
        return await self.authenticate(token, pool)


@lru_cache
def get_auth_service() -> AuthService:
    """Get the singleton AuthService instance."""
    return AuthService(
        authenticators=[
            PersonalApiKeyAuthenticator(),
            OAuthAccessTokenAuthenticator(),
        ],
        cache=get_auth_cache(),
    )
