from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from llm_gateway.auth.authenticators import (
    OAuthAccessTokenAuthenticator,
    PersonalApiKeyAuthenticator,
)
from llm_gateway.auth.cache import AuthCache, reset_auth_cache
from llm_gateway.auth.service import (
    PROJECT_SCOPE_DENIAL_TTL_SECONDS,
    AuthService,
    InvalidProjectScopeError,
    UnauthorizedProjectScopeError,
    extract_token,
    upstream_auth_header,
)


@pytest.fixture(autouse=True)
def reset_cache() -> Generator[None]:
    reset_auth_cache()
    yield
    reset_auth_cache()


@pytest.fixture
def mock_pool() -> MagicMock:
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    return pool


@pytest.fixture
def auth_service() -> AuthService:
    return AuthService(
        authenticators=[
            PersonalApiKeyAuthenticator(),
            OAuthAccessTokenAuthenticator(),
        ],
        cache=AuthCache(max_size=100, ttl=60),
    )


class TestExtractToken:
    @pytest.mark.parametrize(
        "auth_header,expected",
        [
            pytest.param("Bearer test_token", "test_token", id="standard_bearer"),
            pytest.param("bearer test_token", "test_token", id="lowercase_bearer"),
            pytest.param("BEARER test_token", "test_token", id="uppercase_bearer"),
            pytest.param("Bearer   spaced_token", "spaced_token", id="leading_whitespace_trimmed"),
            pytest.param("Basic test_token", None, id="basic_auth_rejected"),
            pytest.param("", None, id="empty_header"),
            pytest.param("Bearer", None, id="bearer_without_token"),
        ],
    )
    def test_bearer_token_extraction(self, auth_header: str, expected: str | None) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"authorization": auth_header} if auth_header else {}
        assert extract_token(request) == expected

    @pytest.mark.parametrize(
        "api_key,expected",
        [
            pytest.param("phx_test_key", "phx_test_key", id="personal_api_key"),
            pytest.param("pha_oauth_token", "pha_oauth_token", id="oauth_token"),
            pytest.param("  spaced_key  ", "spaced_key", id="whitespace_trimmed"),
        ],
    )
    def test_x_api_key_extraction(self, api_key: str, expected: str) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"x-api-key": api_key}
        assert extract_token(request) == expected

    def test_x_api_key_takes_precedence_over_bearer(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"x-api-key": "api_key_token", "authorization": "Bearer bearer_token"}
        assert extract_token(request) == "api_key_token"

    def test_missing_headers_returns_none(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        assert extract_token(request) is None


class TestUpstreamAuthHeader:
    @pytest.mark.parametrize(
        "headers,expected",
        [
            pytest.param({"authorization": "Bearer tok"}, "Bearer tok", id="standard_bearer"),
            pytest.param({"authorization": "bearer tok"}, "Bearer tok", id="lowercase_scheme_canonicalized"),
            pytest.param({"authorization": "BEARER  tok"}, "Bearer tok", id="uppercase_scheme_canonicalized"),
            pytest.param({"x-api-key": " tok "}, "Bearer tok", id="x_api_key_wrapped"),
            pytest.param({"x-api-key": "key", "authorization": "Bearer other"}, "Bearer key", id="x_api_key_wins"),
            pytest.param({"authorization": "Basic abc"}, "Basic abc", id="non_bearer_forwarded_verbatim"),
            pytest.param({}, "", id="no_credential"),
        ],
    )
    def test_forwarded_header(self, headers: dict[str, str], expected: str) -> None:
        request = MagicMock(spec=Request)
        request.headers = headers
        assert upstream_auth_header(request) == expected


def _token_row(**overrides) -> dict:
    row = {
        "id": 1,
        "user_id": 123,
        "scope": "llm_gateway:read",
        "expires": datetime.now(UTC) + timedelta(hours=1),
        "current_team_id": 456,
        "application_id": 789,
        "distinct_id": "test-distinct-id",
        "is_staff": False,
        "scoped_teams": None,
        "scoped_organizations": None,
    }
    row.update(overrides)
    return row


def _project_row(project_id: int, membership_level: int = 1, features: list[str] | None = None) -> dict:
    return {
        "id": project_id,
        "organization_id": "org-2",
        "membership_id": "mem-1",
        "membership_level": membership_level,
        "available_product_features": features,
    }


class TestAuthService:
    @pytest.mark.asyncio
    async def test_missing_token_returns_none(self, auth_service: AuthService, mock_pool: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}

        result = await auth_service.authenticate_request(request, mock_pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_routes_oauth_token_to_oauth_validator(self, auth_service: AuthService, mock_pool: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer pha_valid_token"}

        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "llm_gateway:read",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
            }
        )

        result = await auth_service.authenticate_request(request, mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id == 456
        assert result.auth_method == "oauth_access_token"

    @pytest.mark.asyncio
    async def test_routes_personal_api_key_to_key_validator(
        self, auth_service: AuthService, mock_pool: MagicMock
    ) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"x-api-key": "phx_valid_key"}

        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "k1",
                "user_id": 789,
                "scopes": ["llm_gateway:read"],
                "current_team_id": 101,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
            }
        )

        result = await auth_service.authenticate_request(request, mock_pool)

        assert result is not None
        assert result.user_id == 789
        assert result.team_id == 101
        assert result.auth_method == "personal_api_key"

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self, auth_service: AuthService, mock_pool: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer phx_unknown_key"}

        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(return_value=None)

        result = await auth_service.authenticate_request(request, mock_pool)
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scoped_teams,scoped_organizations",
        [
            pytest.param([789], [], id="team_scope"),
            pytest.param([], ["org-2"], id="organization_scope"),
            pytest.param([], [], id="unrestricted_empty_scope"),
            pytest.param(None, None, id="unrestricted_null_scope"),
        ],
    )
    async def test_oauth_project_scope_overrides_current_team_when_authorized(
        self,
        auth_service: AuthService,
        mock_pool: MagicMock,
        scoped_teams: list[int] | None,
        scoped_organizations: list[str] | None,
    ) -> None:
        request = MagicMock(spec=Request)
        request.headers = {
            "authorization": "Bearer pha_valid_token",
            "x-posthog-project-id": "789",
        }
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            side_effect=[
                {
                    "id": 1,
                    "user_id": 123,
                    "scope": "llm_gateway:read",
                    "expires": datetime.now(UTC) + timedelta(hours=1),
                    "current_team_id": 456,
                    "application_id": 789,
                    "distinct_id": "test-distinct-id",
                    "is_staff": False,
                    "scoped_teams": scoped_teams,
                    "scoped_organizations": scoped_organizations,
                },
                {
                    "id": 789,
                    "organization_id": "org-2",
                    "membership_id": "mem-1",
                    "membership_level": 1,
                    "available_product_features": None,
                },
            ]
        )

        result = await auth_service.authenticate_request(request, mock_pool)

        assert result is not None
        assert result.team_id == 789

    @pytest.mark.asyncio
    async def test_oauth_project_scope_rejects_project_outside_token_scope(
        self, auth_service: AuthService, mock_pool: MagicMock
    ) -> None:
        request = MagicMock(spec=Request)
        request.headers = {
            "authorization": "Bearer pha_valid_token",
            "x-posthog-project-id": "789",
        }
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            side_effect=[
                {
                    "id": 1,
                    "user_id": 123,
                    "scope": "llm_gateway:read",
                    "expires": datetime.now(UTC) + timedelta(hours=1),
                    "current_team_id": 456,
                    "application_id": 789,
                    "distinct_id": "test-distinct-id",
                    "is_staff": False,
                    "scoped_teams": [],
                    "scoped_organizations": ["org-1"],
                },
                {
                    "id": 789,
                    "organization_id": "org-2",
                    "membership_id": "mem-1",
                    "membership_level": 1,
                    "available_product_features": None,
                },
            ]
        )

        with pytest.raises(UnauthorizedProjectScopeError):
            await auth_service.authenticate_request(request, mock_pool)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "project_id",
        [
            pytest.param("not-a-project", id="not_an_integer"),
            pytest.param("2147483648", id="above_postgres_integer_range"),
        ],
    )
    async def test_oauth_project_scope_rejects_malformed_project_id(
        self, auth_service: AuthService, mock_pool: MagicMock, project_id: str
    ) -> None:
        request = MagicMock(spec=Request)
        request.headers = {
            "authorization": "Bearer pha_valid_token",
            "x-posthog-project-id": project_id,
        }
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "llm_gateway:read",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
                "scoped_teams": [456],
                "scoped_organizations": ["org-1"],
            }
        )

        with pytest.raises(InvalidProjectScopeError):
            await auth_service.authenticate_request(request, mock_pool)

    @pytest.mark.asyncio
    async def test_oauth_project_scope_decision_is_cached_per_project(
        self, auth_service: AuthService, mock_pool: MagicMock
    ) -> None:
        def request_for(project_id: str) -> MagicMock:
            request = MagicMock(spec=Request)
            request.headers = {
                "authorization": "Bearer pha_valid_token",
                "x-posthog-project-id": project_id,
            }
            return request

        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            side_effect=[
                {
                    "id": 1,
                    "user_id": 123,
                    "scope": "llm_gateway:read",
                    "expires": datetime.now(UTC) + timedelta(hours=1),
                    "current_team_id": 456,
                    "application_id": 789,
                    "distinct_id": "test-distinct-id",
                    "is_staff": False,
                    "scoped_teams": None,
                    "scoped_organizations": None,
                },
                {
                    "id": 789,
                    "organization_id": "org-2",
                    "membership_id": "mem-1",
                    "membership_level": 1,
                    "available_product_features": None,
                },
                {
                    "id": 790,
                    "organization_id": "org-2",
                    "membership_id": "mem-1",
                    "membership_level": 1,
                    "available_product_features": None,
                },
            ]
        )

        first = await auth_service.authenticate_request(request_for("789"), mock_pool)
        repeat = await auth_service.authenticate_request(request_for("789"), mock_pool)
        other_project = await auth_service.authenticate_request(request_for("790"), mock_pool)

        assert first is not None and first.team_id == 789
        assert repeat is not None and repeat.team_id == 789
        assert other_project is not None and other_project.team_id == 790
        assert conn.fetchrow.await_count == 3

    @pytest.mark.asyncio
    async def test_oauth_project_scope_denial_is_cached(self, auth_service: AuthService, mock_pool: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {
            "authorization": "Bearer pha_valid_token",
            "x-posthog-project-id": "999",
        }
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            side_effect=[
                {
                    "id": 1,
                    "user_id": 123,
                    "scope": "llm_gateway:read",
                    "expires": datetime.now(UTC) + timedelta(hours=1),
                    "current_team_id": 456,
                    "application_id": 789,
                    "distinct_id": "test-distinct-id",
                    "is_staff": False,
                    "scoped_teams": None,
                    "scoped_organizations": None,
                },
                None,
                {
                    "id": 999,
                    "organization_id": "org-2",
                    "membership_id": "mem-1",
                    "membership_level": 1,
                    "available_product_features": None,
                },
            ]
        )

        clock = {"now": 1000.0}
        with patch("llm_gateway.auth.cache.time.monotonic", side_effect=lambda: clock["now"]):
            with pytest.raises(UnauthorizedProjectScopeError):
                await auth_service.authenticate_request(request, mock_pool)
            with pytest.raises(UnauthorizedProjectScopeError):
                await auth_service.authenticate_request(request, mock_pool)
            assert conn.fetchrow.await_count == 2

            clock["now"] += PROJECT_SCOPE_DENIAL_TTL_SECONDS + 1
            granted = await auth_service.authenticate_request(request, mock_pool)

        assert granted is not None
        assert granted.team_id == 999
        assert conn.fetchrow.await_count == 3

    @pytest.mark.asyncio
    async def test_oauth_project_scope_enforces_both_ceilings_when_both_set(
        self, auth_service: AuthService, mock_pool: MagicMock
    ) -> None:
        def request_for(project_id: str) -> MagicMock:
            request = MagicMock(spec=Request)
            request.headers = {
                "authorization": "Bearer pha_valid_token",
                "x-posthog-project-id": project_id,
            }
            return request

        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            side_effect=[
                _token_row(scoped_teams=[789], scoped_organizations=["org-2"]),
                _project_row(790),
                _project_row(789),
            ]
        )

        with pytest.raises(UnauthorizedProjectScopeError):
            await auth_service.authenticate_request(request_for("790"), mock_pool)

        allowed = await auth_service.authenticate_request(request_for("789"), mock_pool)
        assert allowed is not None
        assert allowed.team_id == 789

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "access_rows,role_rows,features,expected_team",
        [
            pytest.param(
                [{"access_level": "none", "organization_member_id": None, "role_id": None}],
                None,
                ['{"key": "access_control"}'],
                None,
                id="restricted_default_denies",
            ),
            pytest.param(
                [
                    {"access_level": "none", "organization_member_id": None, "role_id": None},
                    {"access_level": "member", "organization_member_id": "mem-1", "role_id": None},
                ],
                None,
                ['{"key": "access_control"}'],
                789,
                id="member_grant_allows",
            ),
            pytest.param(
                [
                    {"access_level": "none", "organization_member_id": None, "role_id": None},
                    {"access_level": "member", "organization_member_id": "mem-other", "role_id": None},
                ],
                None,
                ['{"key": "access_control"}'],
                None,
                id="other_members_grant_does_not_allow",
            ),
            pytest.param(
                [
                    {"access_level": "none", "organization_member_id": None, "role_id": None},
                    {"access_level": "member", "organization_member_id": None, "role_id": "role-1"},
                ],
                [{"role_id": "role-1"}],
                ['{"key": "access_control"}', '{"key": "role_based_access"}'],
                789,
                id="role_grant_allows",
            ),
            pytest.param(
                [
                    {"access_level": "none", "organization_member_id": None, "role_id": None},
                    {"access_level": "member", "organization_member_id": None, "role_id": "role-1"},
                ],
                [{"role_id": "role-other"}],
                ['{"key": "access_control"}', '{"key": "role_based_access"}'],
                None,
                id="unheld_role_grant_does_not_allow",
            ),
            pytest.param(
                [
                    {"access_level": "none", "organization_member_id": None, "role_id": None},
                    {"access_level": "member", "organization_member_id": None, "role_id": "role-1"},
                ],
                None,
                ['{"key": "access_control"}'],
                None,
                id="role_grant_inert_without_rbac_feature",
            ),
            pytest.param(
                [
                    {"access_level": "member", "organization_member_id": None, "role_id": None},
                    {"access_level": "none", "organization_member_id": "mem-1", "role_id": None},
                ],
                None,
                ['{"key": "access_control"}'],
                None,
                id="explicit_member_denial_overrides_open_default",
            ),
            pytest.param(
                [{"access_level": "none", "organization_member_id": "mem-1", "role_id": None}],
                None,
                ['{"key": "access_control"}'],
                None,
                id="explicit_member_denial_without_default",
            ),
            pytest.param(
                [
                    {"access_level": "none", "organization_member_id": "mem-1", "role_id": None},
                    {"access_level": "member", "organization_member_id": None, "role_id": "role-1"},
                ],
                [{"role_id": "role-1"}],
                ['{"key": "access_control"}', '{"key": "role_based_access"}'],
                789,
                id="role_grant_outranks_member_denial",
            ),
        ],
    )
    async def test_oauth_project_scope_applies_project_access_control(
        self,
        auth_service: AuthService,
        mock_pool: MagicMock,
        access_rows: list[dict],
        role_rows: list[dict] | None,
        features: list[str],
        expected_team: int | None,
    ) -> None:
        request = MagicMock(spec=Request)
        request.headers = {
            "authorization": "Bearer pha_valid_token",
            "x-posthog-project-id": "789",
        }
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            side_effect=[
                _token_row(),
                _project_row(789, features=features),
            ]
        )
        conn.fetch = AsyncMock(side_effect=[access_rows] + ([role_rows] if role_rows is not None else []))

        if expected_team is None:
            with pytest.raises(UnauthorizedProjectScopeError):
                await auth_service.authenticate_request(request, mock_pool)
        else:
            result = await auth_service.authenticate_request(request, mock_pool)
            assert result is not None
            assert result.team_id == expected_team

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "membership_level,features",
        [
            pytest.param(8, ['{"key": "access_control"}'], id="org_admin_bypasses_rbac"),
            pytest.param(1, None, id="rbac_rows_ignored_without_entitlement"),
        ],
    )
    async def test_oauth_project_scope_skips_access_control_rows(
        self,
        auth_service: AuthService,
        mock_pool: MagicMock,
        membership_level: int,
        features: list[str] | None,
    ) -> None:
        request = MagicMock(spec=Request)
        request.headers = {
            "authorization": "Bearer pha_valid_token",
            "x-posthog-project-id": "789",
        }
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            side_effect=[
                _token_row(),
                _project_row(789, membership_level=membership_level, features=features),
            ]
        )
        conn.fetch = AsyncMock()

        result = await auth_service.authenticate_request(request, mock_pool)

        assert result is not None
        assert result.team_id == 789
        conn.fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_oauth_project_scope_cache_hit_rebinds_current_user(
        self, auth_service: AuthService, mock_pool: MagicMock
    ) -> None:
        request = MagicMock(spec=Request)
        request.headers = {
            "authorization": "Bearer pha_valid_token",
            "x-posthog-project-id": "789",
        }
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(side_effect=[_token_row(), _project_row(789)])

        first = await auth_service.authenticate_request(request, mock_pool)
        assert first is not None
        assert first.is_staff is False

        token_hash = OAuthAccessTokenAuthenticator().hash_token("pha_valid_token")
        auth_service._cache.set(token_hash, replace(first, team_id=456, is_staff=True), ttl=60)

        second = await auth_service.authenticate_request(request, mock_pool)

        assert second is not None
        assert second.is_staff is True
        assert second.team_id == 789
        assert conn.fetchrow.await_count == 2


class TestPersonalApiKeyAuthenticator:
    @pytest.fixture
    def authenticator(self) -> PersonalApiKeyAuthenticator:
        return PersonalApiKeyAuthenticator()

    @pytest.mark.parametrize(
        "key,expected_prefix,expected_length",
        [
            pytest.param("test_key", "sha256$", 71, id="standard_key"),
            pytest.param("", "sha256$", 71, id="empty_key"),
            pytest.param("a" * 1000, "sha256$", 71, id="long_key"),
        ],
    )
    def test_hash_format(
        self, authenticator: PersonalApiKeyAuthenticator, key: str, expected_prefix: str, expected_length: int
    ) -> None:
        result = authenticator.hash_token(key)
        assert result.startswith(expected_prefix)
        assert len(result) == expected_length

    def test_hash_is_deterministic(self, authenticator: PersonalApiKeyAuthenticator) -> None:
        key = "test_key"
        assert authenticator.hash_token(key) == authenticator.hash_token(key)

    @pytest.mark.parametrize(
        "key1,key2",
        [
            pytest.param("key1", "key2", id="different_keys"),
            pytest.param("KEY", "key", id="case_sensitive"),
        ],
    )
    def test_different_keys_produce_different_hashes(
        self, authenticator: PersonalApiKeyAuthenticator, key1: str, key2: str
    ) -> None:
        assert authenticator.hash_token(key1) != authenticator.hash_token(key2)

    def test_matches_phx_prefix(self, authenticator: PersonalApiKeyAuthenticator) -> None:
        assert authenticator.matches("phx_test_key") is True
        assert authenticator.matches("pha_oauth_token") is False
        assert authenticator.matches("random_token") is False

    @pytest.mark.asyncio
    async def test_valid_key_returns_authenticated_user(
        self, authenticator: PersonalApiKeyAuthenticator, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "k1",
                "user_id": 123,
                "scopes": ["llm_gateway:read"],
                "current_team_id": 456,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
            }
        )

        token_hash = authenticator.hash_token("phx_test_key")
        result = await authenticator.authenticate(token_hash, mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id == 456
        assert result.auth_method == "personal_api_key"
        assert result.is_staff is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "db_result",
        [
            pytest.param(None, id="key_not_found"),
            pytest.param(
                {"id": "k1", "user_id": 123, "scopes": ["read:only"], "current_team_id": 456},
                id="missing_required_scope",
            ),
            pytest.param(
                {"id": "k2", "user_id": 789, "scopes": None, "current_team_id": None},
                id="null_scopes",
            ),
            pytest.param(
                {"id": "k3", "user_id": 100, "scopes": [], "current_team_id": 200},
                id="empty_scopes",
            ),
            pytest.param(
                {"id": "k4", "user_id": 101, "scopes": ["*"], "current_team_id": 201},
                id="wildcard_scope_rejected",
            ),
        ],
    )
    async def test_invalid_keys_return_none(
        self,
        authenticator: PersonalApiKeyAuthenticator,
        mock_pool: MagicMock,
        db_result: dict[str, object] | None,
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(return_value=db_result)

        token_hash = authenticator.hash_token("phx_invalid_key")
        result = await authenticator.authenticate(token_hash, mock_pool)
        assert result is None


class TestOAuthAccessTokenAuthenticator:
    @pytest.fixture
    def authenticator(self) -> OAuthAccessTokenAuthenticator:
        return OAuthAccessTokenAuthenticator()

    def test_matches_pha_prefix(self, authenticator: OAuthAccessTokenAuthenticator) -> None:
        assert authenticator.matches("pha_oauth_token") is True
        assert authenticator.matches("phx_personal_key") is False
        assert authenticator.matches("random_token") is False

    @pytest.mark.asyncio
    async def test_token_not_found_returns_none(
        self, authenticator: OAuthAccessTokenAuthenticator, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(return_value=None)

        token_hash = authenticator.hash_token("pha_unknown_token")
        result = await authenticator.authenticate(token_hash, mock_pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(
        self, authenticator: OAuthAccessTokenAuthenticator, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "llm_gateway:read",
                "expires": datetime.now(UTC) - timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
                "distinct_id": "test-distinct-id",
            }
        )

        token_hash = authenticator.hash_token("pha_expired_token")
        result = await authenticator.authenticate(token_hash, mock_pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_token_without_expiry_is_valid(
        self, authenticator: OAuthAccessTokenAuthenticator, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "llm_gateway:read",
                "expires": None,
                "current_team_id": 456,
                "application_id": 789,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
            }
        )

        token_hash = authenticator.hash_token("pha_no_expiry")
        result = await authenticator.authenticate(token_hash, mock_pool)

        assert result is not None
        assert result.user_id == 123

    @pytest.mark.asyncio
    async def test_missing_application_id_returns_none(
        self, authenticator: OAuthAccessTokenAuthenticator, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "llm_gateway:read",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": None,
                "distinct_id": "test-distinct-id",
            }
        )

        token_hash = authenticator.hash_token("pha_no_app_id")
        result = await authenticator.authenticate(token_hash, mock_pool)
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scope",
        [
            pytest.param(None, id="null_scope"),
            pytest.param("", id="empty_scope"),
            pytest.param("read:only", id="wrong_scope"),
            pytest.param("task:read", id="read_not_write"),
        ],
    )
    async def test_missing_task_write_scope_returns_none(
        self, authenticator: OAuthAccessTokenAuthenticator, mock_pool: MagicMock, scope: str | None
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": scope,
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
                "distinct_id": "test-distinct-id",
            }
        )

        token_hash = authenticator.hash_token("pha_wrong_scope")
        result = await authenticator.authenticate(token_hash, mock_pool)
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scope,expected_scopes",
        [
            pytest.param("llm_gateway:read", ["llm_gateway:read"], id="single_scope"),
            pytest.param("llm_gateway:read task:read", ["llm_gateway:read", "task:read"], id="multiple_scopes"),
            pytest.param(
                "read:all llm_gateway:read admin", ["read:all", "llm_gateway:read", "admin"], id="three_scopes"
            ),
            pytest.param("*", ["*"], id="wildcard_scope_accepted_for_oauth"),
        ],
    )
    async def test_scope_parsing(
        self, authenticator: OAuthAccessTokenAuthenticator, mock_pool: MagicMock, scope: str, expected_scopes: list[str]
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": scope,
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
            }
        )

        token_hash = authenticator.hash_token("pha_valid_token")
        result = await authenticator.authenticate(token_hash, mock_pool)

        assert result is not None
        assert result.scopes == expected_scopes

    @pytest.mark.asyncio
    async def test_valid_token_returns_authenticated_user(
        self, authenticator: OAuthAccessTokenAuthenticator, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "llm_gateway:read",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
                "distinct_id": "test-distinct-id",
                "is_staff": True,
            }
        )

        token_hash = authenticator.hash_token("pha_valid_token")
        result = await authenticator.authenticate(token_hash, mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id == 456
        assert result.auth_method == "oauth_access_token"
        assert result.scopes == ["llm_gateway:read"]
        assert result.is_staff is True

    @pytest.mark.asyncio
    async def test_valid_token_with_null_team_id(
        self, authenticator: OAuthAccessTokenAuthenticator, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "llm_gateway:read",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": None,
                "application_id": 789,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
            }
        )

        token_hash = authenticator.hash_token("pha_valid_token")
        result = await authenticator.authenticate(token_hash, mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id is None
