from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request

from llm_gateway.auth.authenticators import (
    OAuthAccessTokenAuthenticator,
    PersonalApiKeyAuthenticator,
)
from llm_gateway.auth.cache import AuthCache, reset_auth_cache
from llm_gateway.auth.service import AuthService, extract_token


@pytest.fixture(autouse=True)
def reset_cache() -> Generator[None, None, None]:
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
            }
        )

        token_hash = authenticator.hash_token("phx_test_key")
        result = await authenticator.authenticate(token_hash, mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id == 456
        assert result.auth_method == "personal_api_key"

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
        ],
    )
    async def test_invalid_keys_return_none(
        self, authenticator: PersonalApiKeyAuthenticator, mock_pool: MagicMock, db_result: dict | None
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
            }
        )

        token_hash = authenticator.hash_token("pha_valid_token")
        result = await authenticator.authenticate(token_hash, mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id == 456
        assert result.auth_method == "oauth_access_token"
        assert result.scopes == ["llm_gateway:read"]

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
            }
        )

        token_hash = authenticator.hash_token("pha_valid_token")
        result = await authenticator.authenticate(token_hash, mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id is None
