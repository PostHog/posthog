import hashlib
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import asyncpg

from llm_gateway.auth.models import AuthenticatedUser, has_required_scope
from llm_gateway.db.postgres import acquire_connection


class Authenticator(ABC):
    """Abstract base class for token authenticators - pure DB lookup, no side effects."""

    @property
    @abstractmethod
    def auth_type(self) -> str:
        """Identifier for this auth type (used in metrics)."""
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

    def matches(self, token: str) -> bool:
        return token.startswith("phx_")

    def hash_token(self, token: str) -> str:
        hashed = hashlib.sha256(token.encode()).hexdigest()
        return f"sha256${hashed}"

    async def authenticate(self, token_hash: str, pool: asyncpg.Pool) -> AuthenticatedUser | None:
        async with acquire_connection(pool) as conn:
            row = await conn.fetchrow(
                """
                SELECT pak.id, pak.user_id, pak.scopes, u.current_team_id
                FROM posthog_personalapikey pak
                JOIN posthog_user u ON pak.user_id = u.id
                WHERE pak.secure_value = $1 AND u.is_active = true
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
                scopes=scopes,
            )


class OAuthAccessTokenAuthenticator(Authenticator):
    """Authenticator for OAuth access tokens (pha_ prefix)."""

    @property
    def auth_type(self) -> str:
        return "oauth_access_token"

    def matches(self, token: str) -> bool:
        return token.startswith("pha_")

    def hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def authenticate(self, token_hash: str, pool: asyncpg.Pool) -> AuthenticatedUser | None:
        async with acquire_connection(pool) as conn:
            row = await conn.fetchrow(
                """
                SELECT oat.id, oat.user_id, oat.scope, oat.expires,
                       u.current_team_id, oat.application_id
                FROM posthog_oauthaccesstoken oat
                JOIN posthog_user u ON oat.user_id = u.id
                WHERE oat.token_checksum = $1 AND u.is_active = true
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
            if not has_required_scope(scopes):
                return None

            return AuthenticatedUser(
                user_id=row["user_id"],
                team_id=row["current_team_id"],
                auth_method=self.auth_type,
                scopes=scopes,
                token_expires_at=expires,
            )
