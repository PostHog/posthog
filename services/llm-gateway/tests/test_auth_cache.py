import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_gateway.auth.authenticators import OAuthAccessTokenAuthenticator, PersonalApiKeyAuthenticator
from llm_gateway.auth.cache import AuthCache, reset_auth_cache
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.auth.service import AuthService


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


class TestAuthCache:
    def test_cache_miss_returns_false(self) -> None:
        cache = AuthCache(max_size=100, ttl=60)
        hit, user = cache.get("nonexistent_key")
        assert hit is False
        assert user is None

    def test_cache_set_and_get(self) -> None:
        cache = AuthCache(max_size=100, ttl=60)
        user = AuthenticatedUser(
            user_id=1, team_id=2, auth_method="test", distinct_id="test-distinct-id", scopes=["read"]
        )

        cache.set("key1", user)
        hit, cached_user = cache.get("key1")

        assert hit is True
        assert cached_user == user

    def test_cache_expiry(self) -> None:
        cache = AuthCache(max_size=100, ttl=1)
        user = AuthenticatedUser(
            user_id=1, team_id=2, auth_method="test", distinct_id="test-distinct-id", scopes=["read"]
        )

        cache.set("key1", user)

        hit, _ = cache.get("key1")
        assert hit is True

        time.sleep(1.1)

        hit, cached_user = cache.get("key1")
        assert hit is False
        assert cached_user is None

    def test_negative_cache(self) -> None:
        cache = AuthCache(max_size=100, ttl=60)

        cache.set("bad_key", None)
        hit, user = cache.get("bad_key")

        assert hit is True
        assert user is None

    def test_invalidate(self) -> None:
        cache = AuthCache(max_size=100, ttl=60)
        user = AuthenticatedUser(
            user_id=1, team_id=2, auth_method="test", distinct_id="test-distinct-id", scopes=["read"]
        )

        cache.set("key1", user)
        cache.invalidate("key1")

        hit, _ = cache.get("key1")
        assert hit is False

    def test_clear(self) -> None:
        cache = AuthCache(max_size=100, ttl=60)
        user = AuthenticatedUser(
            user_id=1, team_id=2, auth_method="test", distinct_id="test-distinct-id", scopes=["read"]
        )

        cache.set("key1", user)
        cache.set("key2", user)
        assert cache.size == 2

        cache.clear()
        assert cache.size == 0

    def test_lru_eviction(self) -> None:
        cache = AuthCache(max_size=2, ttl=60)
        user1 = AuthenticatedUser(user_id=1, team_id=1, auth_method="test", distinct_id="test-1", scopes=["read"])
        user2 = AuthenticatedUser(user_id=2, team_id=2, auth_method="test", distinct_id="test-2", scopes=["read"])
        user3 = AuthenticatedUser(user_id=3, team_id=3, auth_method="test", distinct_id="test-3", scopes=["read"])

        cache.set("key1", user1)
        cache.set("key2", user2)
        cache.set("key3", user3)

        assert cache.size == 2
        hit, _ = cache.get("key1")
        assert hit is False

    def test_token_expiry_returns_miss(self) -> None:
        cache = AuthCache(max_size=100, ttl=60)
        expired_user = AuthenticatedUser(
            user_id=1,
            team_id=2,
            auth_method="oauth_access_token",
            distinct_id="test-distinct-id",
            scopes=["llm_gateway:read"],
            token_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        cache.set("expired_token", expired_user)
        hit, user = cache.get("expired_token")

        assert hit is False
        assert user is None
        assert cache.size == 0

    def test_token_without_expiry_returns_hit(self) -> None:
        cache = AuthCache(max_size=100, ttl=60)
        user = AuthenticatedUser(
            user_id=1,
            team_id=2,
            auth_method="personal_api_key",
            distinct_id="test-distinct-id",
            scopes=["llm_gateway:read"],
            token_expires_at=None,
        )

        cache.set("api_key", user)
        hit, cached_user = cache.get("api_key")

        assert hit is True
        assert cached_user == user

    def test_token_with_future_expiry_returns_hit(self) -> None:
        cache = AuthCache(max_size=100, ttl=60)
        user = AuthenticatedUser(
            user_id=1,
            team_id=2,
            auth_method="oauth_access_token",
            distinct_id="test-distinct-id",
            scopes=["llm_gateway:read"],
            token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        cache.set("valid_token", user)
        hit, cached_user = cache.get("valid_token")

        assert hit is True
        assert cached_user == user


class TestAuthServiceCaching:
    @pytest.fixture
    def auth_service(self) -> AuthService:
        return AuthService(
            authenticators=[
                PersonalApiKeyAuthenticator(),
                OAuthAccessTokenAuthenticator(),
            ],
            cache=AuthCache(max_size=100, ttl=60),
        )

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db_for_personal_api_key(
        self, auth_service: AuthService, mock_pool: MagicMock
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

        result1 = await auth_service.authenticate("phx_test_key", mock_pool)
        assert result1 is not None
        assert conn.fetchrow.call_count == 1

        result2 = await auth_service.authenticate("phx_test_key", mock_pool)
        assert result2 is not None
        assert result2.user_id == 123
        assert conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    async def test_negative_cache_skips_db_for_personal_api_key(
        self, auth_service: AuthService, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(return_value=None)

        result1 = await auth_service.authenticate("phx_invalid_key", mock_pool)
        assert result1 is None
        assert conn.fetchrow.call_count == 1

        result2 = await auth_service.authenticate("phx_invalid_key", mock_pool)
        assert result2 is None
        assert conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    async def test_cache_hit_skips_db_for_oauth_token(self, auth_service: AuthService, mock_pool: MagicMock) -> None:
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

        result1 = await auth_service.authenticate("pha_test_token", mock_pool)
        assert result1 is not None
        assert conn.fetchrow.call_count == 1

        result2 = await auth_service.authenticate("pha_test_token", mock_pool)
        assert result2 is not None
        assert result2.user_id == 123
        assert conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    async def test_negative_cache_skips_db_for_oauth_token(
        self, auth_service: AuthService, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(return_value=None)

        result1 = await auth_service.authenticate("pha_invalid_token", mock_pool)
        assert result1 is None
        assert conn.fetchrow.call_count == 1

        result2 = await auth_service.authenticate("pha_invalid_token", mock_pool)
        assert result2 is None
        assert conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    async def test_token_without_expiry_caches(self, auth_service: AuthService, mock_pool: MagicMock) -> None:
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

        result1 = await auth_service.authenticate("pha_no_expiry", mock_pool)
        assert result1 is not None
        assert conn.fetchrow.call_count == 1

        result2 = await auth_service.authenticate("pha_no_expiry", mock_pool)
        assert result2 is not None
        assert conn.fetchrow.call_count == 1

    @pytest.mark.asyncio
    async def test_unrecognized_token_prefix_returns_none(
        self, auth_service: AuthService, mock_pool: MagicMock
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock()

        result = await auth_service.authenticate("xyz_unknown_prefix", mock_pool)

        assert result is None
        conn.fetchrow.assert_not_called()


class TestAuthServiceMetrics:
    @pytest.fixture
    def auth_service(self) -> AuthService:
        return AuthService(
            authenticators=[
                PersonalApiKeyAuthenticator(),
                OAuthAccessTokenAuthenticator(),
            ],
            cache=AuthCache(max_size=100, ttl=60),
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "token,auth_type",
        [
            pytest.param("phx_test_key", "personal_api_key", id="personal_api_key"),
            pytest.param("pha_test_token", "oauth_access_token", id="oauth_access_token"),
        ],
    )
    async def test_cache_miss_increments_metric(
        self, auth_service: AuthService, mock_pool: MagicMock, token: str, auth_type: str
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scopes": ["llm_gateway:read"],
                "scope": "llm_gateway:read",
                "current_team_id": 456,
                "application_id": 789,
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "distinct_id": "test-distinct-id",
            }
        )

        with patch("llm_gateway.auth.service.AUTH_CACHE_MISSES") as mock_misses:
            await auth_service.authenticate(token, mock_pool)
            mock_misses.labels.assert_called_once_with(auth_type=auth_type)
            mock_misses.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "token,auth_type",
        [
            pytest.param("phx_test_key", "personal_api_key", id="personal_api_key"),
            pytest.param("pha_test_token", "oauth_access_token", id="oauth_access_token"),
        ],
    )
    async def test_cache_hit_increments_metric(
        self, auth_service: AuthService, mock_pool: MagicMock, token: str, auth_type: str
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scopes": ["llm_gateway:read"],
                "scope": "llm_gateway:read",
                "current_team_id": 456,
                "application_id": 789,
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "distinct_id": "test-distinct-id",
            }
        )

        await auth_service.authenticate(token, mock_pool)

        with patch("llm_gateway.auth.service.AUTH_CACHE_HITS") as mock_hits:
            await auth_service.authenticate(token, mock_pool)
            mock_hits.labels.assert_called_once_with(auth_type=auth_type)
            mock_hits.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "token,auth_type",
        [
            pytest.param("phx_invalid", "personal_api_key", id="personal_api_key"),
            pytest.param("pha_invalid", "oauth_access_token", id="oauth_access_token"),
        ],
    )
    async def test_invalid_auth_increments_metric_on_cache_miss(
        self, auth_service: AuthService, mock_pool: MagicMock, token: str, auth_type: str
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("llm_gateway.auth.service.AUTH_INVALID") as mock_invalid:
            await auth_service.authenticate(token, mock_pool)
            mock_invalid.labels.assert_called_once_with(auth_type=auth_type)
            mock_invalid.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "token,auth_type",
        [
            pytest.param("phx_invalid", "personal_api_key", id="personal_api_key"),
            pytest.param("pha_invalid", "oauth_access_token", id="oauth_access_token"),
        ],
    )
    async def test_invalid_auth_increments_metric_on_negative_cache_hit(
        self, auth_service: AuthService, mock_pool: MagicMock, token: str, auth_type: str
    ) -> None:
        conn = mock_pool.acquire.return_value
        conn.fetchrow = AsyncMock(return_value=None)

        await auth_service.authenticate(token, mock_pool)

        with patch("llm_gateway.auth.service.AUTH_INVALID") as mock_invalid:
            await auth_service.authenticate(token, mock_pool)
            mock_invalid.labels.assert_called_once_with(auth_type=auth_type)
            mock_invalid.labels.return_value.inc.assert_called_once()
