import hashlib
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import asyncpg

from llm_gateway.auth.models import AuthenticatedUser, has_required_scope
from llm_gateway.config import get_settings
from llm_gateway.db.postgres import acquire_connection


def _compute_team_ids(row: Any) -> frozenset[int]:
    """Compute the set of team ids the authenticated user can bill against.

    Starts from all teams reachable via the user's organization memberships,
    then intersects with the key/token's `scoped_teams` when that restriction
    is set. A missing / empty `scoped_teams` means no team-scope restriction.
    """
    org_team_ids_raw: Iterable[int] | None = row.get("org_team_ids") if hasattr(row, "get") else None
    if org_team_ids_raw is None:
        org_team_ids_raw = []
    org_team_ids = frozenset(int(t) for t in org_team_ids_raw if t is not None)

    scoped_teams_raw: Iterable[int] | None = row.get("scoped_teams") if hasattr(row, "get") else None
    if scoped_teams_raw:
        scoped_teams = frozenset(int(t) for t in scoped_teams_raw if t is not None)
        return org_team_ids & scoped_teams
    return org_team_ids


class Authenticator(ABC):
    """Abstract base class for token authenticators - pure DB lookup, no side effects."""

    @property
    @abstractmethod
    def auth_type(self) -> str:
        """Identifier for this auth type (used in metrics)."""
        ...

    @property
    @abstractmethod
    def cache_ttl(self) -> int:
        """How long successful auth results should be cached (seconds)."""
        ...

    @abstractmethod
    def matches(self, token: str) -> bool:
        """Check if this authenticator handles this token format."""
        ...

    @abstractmethod
    def hash_token(self, token: str) -> str:
        """Hash the token for DB lookup and cache key."""
        ...

    @abstractmethod
    async def authenticate(self, token_hash: str, pool: asyncpg.Pool) -> AuthenticatedUser | None:
        """Perform DB lookup. Returns None if invalid."""
        ...


class PersonalApiKeyAuthenticator(Authenticator):
    """Authenticator for personal API keys (phx_ prefix)."""

    @property
    def auth_type(self) -> str:
        return "personal_api_key"

    @property
    def cache_ttl(self) -> int:
        return get_settings().auth_cache_ttl

    def matches(self, token: str) -> bool:
        return token.startswith("phx_")

    def hash_token(self, token: str) -> str:
        hashed = hashlib.sha256(token.encode()).hexdigest()
        return f"sha256${hashed}"

    async def authenticate(self, token_hash: str, pool: asyncpg.Pool) -> AuthenticatedUser | None:
        async with acquire_connection(pool) as conn:
            row = await conn.fetchrow(
                """
                SELECT pak.id,
                       pak.user_id,
                       pak.scopes,
                       pak.scoped_teams,
                       u.current_team_id,
                       u.distinct_id,
                       COALESCE(
                           array_agg(DISTINCT t.id) FILTER (WHERE t.id IS NOT NULL),
                           ARRAY[]::integer[]
                       ) AS org_team_ids
                FROM posthog_personalapikey pak
                JOIN posthog_user u ON pak.user_id = u.id
                LEFT JOIN posthog_organizationmembership om ON om.user_id = u.id
                LEFT JOIN posthog_team t ON t.organization_id = om.organization_id
                WHERE pak.secure_value = $1 AND u.is_active = true
                GROUP BY pak.id, pak.user_id, pak.scopes, pak.scoped_teams, u.current_team_id, u.distinct_id
                """,
                token_hash,
            )

            if not row:
                return None

            scopes = row["scopes"] or []
            if not has_required_scope(scopes):
                return None

            return AuthenticatedUser(
                user_id=row["user_id"],
                team_id=row["current_team_id"],
                auth_method=self.auth_type,
                distinct_id=row["distinct_id"],
                scopes=scopes,
                team_ids=_compute_team_ids(row),
            )


class OAuthAccessTokenAuthenticator(Authenticator):
    """Authenticator for OAuth access tokens (pha_ prefix)."""

    @property
    def auth_type(self) -> str:
        return "oauth_access_token"

    @property
    def cache_ttl(self) -> int:
        return get_settings().auth_cache_ttl_oauth

    def matches(self, token: str) -> bool:
        return token.startswith("pha_")

    def hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def authenticate(self, token_hash: str, pool: asyncpg.Pool) -> AuthenticatedUser | None:
        async with acquire_connection(pool) as conn:
            row = await conn.fetchrow(
                """
                SELECT oat.id,
                       oat.user_id,
                       oat.scope,
                       oat.expires,
                       oat.application_id,
                       oat.scoped_teams,
                       u.current_team_id,
                       u.distinct_id,
                       COALESCE(
                           array_agg(DISTINCT t.id) FILTER (WHERE t.id IS NOT NULL),
                           ARRAY[]::integer[]
                       ) AS org_team_ids
                FROM posthog_oauthaccesstoken oat
                JOIN posthog_user u ON oat.user_id = u.id
                LEFT JOIN posthog_organizationmembership om ON om.user_id = u.id
                LEFT JOIN posthog_team t ON t.organization_id = om.organization_id
                WHERE oat.token_checksum = $1 AND u.is_active = true
                GROUP BY oat.id, oat.user_id, oat.scope, oat.expires, oat.application_id,
                         oat.scoped_teams, u.current_team_id, u.distinct_id
                """,
                token_hash,
            )

            if not row:
                return None

            expires: datetime | None = row["expires"]
            if expires and expires < datetime.now(UTC):
                return None

            if not row["application_id"]:
                return None

            scopes = row["scope"].split() if row["scope"] else []
            if not has_required_scope(scopes, allow_wildcard=True):
                return None

            return AuthenticatedUser(
                user_id=row["user_id"],
                team_id=row["current_team_id"],
                auth_method=self.auth_type,
                distinct_id=row["distinct_id"],
                scopes=scopes,
                token_expires_at=expires,
                application_id=str(row["application_id"]),
                team_ids=_compute_team_ids(row),
            )
