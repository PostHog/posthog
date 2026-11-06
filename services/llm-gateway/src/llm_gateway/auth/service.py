import json
import re
from dataclasses import replace
from functools import lru_cache

import asyncpg
from fastapi import Request

from llm_gateway.auth.authenticators import Authenticator, OAuthAccessTokenAuthenticator, PersonalApiKeyAuthenticator
from llm_gateway.auth.cache import AuthCache, get_auth_cache
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings
from llm_gateway.db.postgres import acquire_connection
from llm_gateway.metrics.prometheus import AUTH_CACHE_HITS, AUTH_CACHE_MISSES, AUTH_INVALID

BEARER_PATTERN = re.compile(r"^Bearer\s+(\S+)$", re.IGNORECASE)
PROJECT_SCOPE_HEADER = "x-posthog-project-id"
MAX_PROJECT_ID = 2_147_483_647
# Denials expire fast so access granted moments after a failed attempt becomes
# usable within a minute, while the short window still absorbs repeated denied
# requests. Allows keep the full OAuth auth TTL.
PROJECT_SCOPE_DENIAL_TTL_SECONDS = 60
ORG_ADMIN_MEMBERSHIP_LEVEL = 8  # OrganizationMembership.Level.ADMIN
_PROJECT_ACCESS_LEVEL_RANK = {"none": 0, "member": 1, "admin": 2}


def _feature_keys(raw: object) -> set[str]:
    """Feature keys from posthog_organization.available_product_features —
    a jsonb[] column, so asyncpg yields each element as a JSON string."""
    if not isinstance(raw, list | tuple):
        return set()
    keys: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except ValueError:
                continue
        if isinstance(item, dict) and isinstance(item.get("key"), str):
            keys.add(item["key"])
    return keys


class InvalidProjectScopeError(Exception):
    pass


class UnauthorizedProjectScopeError(Exception):
    pass


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
    token = extract_token(request)
    if token is None:
        return request.headers.get("authorization", "")
    # Not a route handler: this builds an outbound header value from the
    # caller's own credential; nothing is rendered to a response body.
    # nosemgrep: python.flask.security.audit.directly-returned-format-string.directly-returned-format-string
    return f"Bearer {token}"


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
        user = await self.authenticate(token, pool)
        if user is None or user.auth_method != "oauth_access_token":
            return user

        raw_project_id = request.headers.get(PROJECT_SCOPE_HEADER)
        if raw_project_id is None:
            return user
        try:
            project_id = int(raw_project_id)
        except ValueError as exc:
            raise InvalidProjectScopeError from exc
        if project_id <= 0 or project_id > MAX_PROJECT_ID:
            raise InvalidProjectScopeError

        return await self._resolve_project_scope(user, project_id, token, pool)

    async def _resolve_project_scope(
        self, user: AuthenticatedUser, project_id: int, token: str, pool: asyncpg.Pool
    ) -> AuthenticatedUser:
        """Rebind the user to the selected project when the token's scope
        ceilings, live org membership, and project-level access control allow it.

        Only the allow/deny decision is cached per token-and-project (allows for
        the OAuth auth TTL, denials for PROJECT_SCOPE_DENIAL_TTL_SECONDS so newly
        granted access becomes usable within a minute); the returned user is
        rebuilt from this request's authentication, never the cached snapshot.
        """
        token_hash = next(auth.hash_token(token) for auth in self._authenticators if auth.matches(token))
        cache_key = f"{token_hash}:project:{project_id}"

        hit, cached = self._cache.get(cache_key)
        if hit:
            AUTH_CACHE_HITS.labels(auth_type="oauth_project_scope").inc()
            if cached is None:
                raise UnauthorizedProjectScopeError
            return replace(user, team_id=project_id)
        AUTH_CACHE_MISSES.labels(auth_type="oauth_project_scope").inc()

        if not await self._project_scope_allowed(user, project_id, pool):
            self._cache.set(cache_key, None, ttl=PROJECT_SCOPE_DENIAL_TTL_SECONDS)
            raise UnauthorizedProjectScopeError

        # Stored as a user object so token expiry evicts the entry; reads above
        # use it only as the allow marker.
        self._cache.set(cache_key, replace(user, team_id=project_id), ttl=get_settings().auth_cache_ttl_oauth)
        return replace(user, team_id=project_id)

    async def _project_scope_allowed(self, user: AuthenticatedUser, project_id: int, pool: asyncpg.Pool) -> bool:
        """Mirror of the Django checks a project-nested request passes.

        Scope ceilings follow APIScopePermission.check_team_and_org_permissions:
        scoped_teams and scoped_organizations are independent ceilings, each
        enforced whenever non-empty. Project access follows
        UserAccessControl.get_user_access_level for resource="project": org
        admins bypass, rows apply only when the organization has the
        access_control feature, and no rows means the open project default.
        Rows resolve most-specific-first (_object_access_level_from_rows):
        explicit member and role rows for this user take the highest level
        among themselves and the default row is consulted only when no
        explicit row names the user. Role rows count only when the
        organization also has the role_based_access feature and the user
        holds the role in the project's organization
        (UserAccessControl._user_role_ids).
        """
        async with acquire_connection(pool) as conn:
            project = await conn.fetchrow(
                """
                SELECT t.organization_id, om.id AS membership_id, om.level AS membership_level,
                       o.available_product_features
                FROM posthog_team t
                JOIN posthog_organizationmembership om ON om.organization_id = t.organization_id
                JOIN posthog_organization o ON o.id = t.organization_id
                WHERE t.id = $1 AND om.user_id = $2
                """,
                project_id,
                user.user_id,
            )
            if project is None:
                return False

            scoped_teams = user.scoped_teams or []
            scoped_organizations = user.scoped_organizations or []
            if scoped_teams and project_id not in scoped_teams:
                return False
            if scoped_organizations and str(project["organization_id"]) not in scoped_organizations:
                return False

            if project["membership_level"] >= ORG_ADMIN_MEMBERSHIP_LEVEL:
                return True
            features = _feature_keys(project["available_product_features"])
            if "access_control" not in features:
                return True

            rows = await conn.fetch(
                """
                SELECT access_level, organization_member_id, role_id
                FROM ee_accesscontrol
                WHERE team_id = $1 AND resource = 'project' AND resource_id = $2
                """,
                project_id,
                str(project_id),
            )
            if not rows:
                return True

            default_levels: list[str] = []
            explicit_levels: list[str] = []
            role_grants: dict[str, str] = {}
            for row in rows:
                if row["organization_member_id"] is None and row["role_id"] is None:
                    default_levels.append(row["access_level"])
                elif row["organization_member_id"] is not None:
                    if str(row["organization_member_id"]) == str(project["membership_id"]):
                        explicit_levels.append(row["access_level"])
                elif row["role_id"] is not None:
                    role_grants[str(row["role_id"])] = row["access_level"]

            if role_grants and "role_based_access" in features:
                user_roles = await conn.fetch(
                    """
                    SELECT rm.role_id
                    FROM ee_rolemembership rm
                    JOIN ee_role r ON r.id = rm.role_id
                    WHERE rm.user_id = $1 AND r.organization_id = $2
                    """,
                    user.user_id,
                    project["organization_id"],
                )
                explicit_levels.extend(
                    role_grants[str(row["role_id"])] for row in user_roles if str(row["role_id"]) in role_grants
                )

            levels = explicit_levels or default_levels
            if not levels:
                return True
            return any(_PROJECT_ACCESS_LEVEL_RANK.get(level, 0) > 0 for level in levels)


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
