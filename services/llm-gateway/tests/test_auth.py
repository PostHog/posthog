from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request

from llm_gateway.auth.middleware import authenticate_request, extract_token
from llm_gateway.auth.oauth import validate_oauth_token
from llm_gateway.auth.personal_api_key import hash_key_value_sha256, validate_personal_api_key


@pytest.fixture
def mock_pool() -> MagicMock:
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


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


class TestAuthenticateRequest:
    @pytest.mark.asyncio
    async def test_missing_token_returns_none(self, mock_pool: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}

        result = await authenticate_request(request, mock_pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_routes_oauth_token_to_oauth_validator(self, mock_pool: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer pha_valid_token"}

        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "task:write",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
            }
        )

        result = await authenticate_request(request, mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id == 456
        assert result.auth_method == "oauth"

    @pytest.mark.asyncio
    async def test_routes_personal_api_key_to_key_validator(self, mock_pool: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"x-api-key": "phx_valid_key"}

        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "k1",
                "user_id": 789,
                "scopes": ["task:write"],
                "current_team_id": 101,
            }
        )

        result = await authenticate_request(request, mock_pool)

        assert result is not None
        assert result.user_id == 789
        assert result.team_id == 101
        assert result.auth_method == "personal_api_key"

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self, mock_pool: MagicMock) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"authorization": "Bearer phx_unknown_key"}

        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(return_value=None)

        result = await authenticate_request(request, mock_pool)
        assert result is None


class TestPersonalApiKey:
    @pytest.mark.parametrize(
        "key,expected_prefix,expected_length",
        [
            pytest.param("test_key", "sha256$", 71, id="standard_key"),
            pytest.param("", "sha256$", 71, id="empty_key"),
            pytest.param("a" * 1000, "sha256$", 71, id="long_key"),
        ],
    )
    def test_hash_format(self, key: str, expected_prefix: str, expected_length: int) -> None:
        result = hash_key_value_sha256(key)
        assert result.startswith(expected_prefix)
        assert len(result) == expected_length

    def test_hash_is_deterministic(self) -> None:
        key = "test_key"
        assert hash_key_value_sha256(key) == hash_key_value_sha256(key)

    @pytest.mark.parametrize(
        "key1,key2",
        [
            pytest.param("key1", "key2", id="different_keys"),
            pytest.param("KEY", "key", id="case_sensitive"),
        ],
    )
    def test_different_keys_produce_different_hashes(self, key1: str, key2: str) -> None:
        assert hash_key_value_sha256(key1) != hash_key_value_sha256(key2)

    @pytest.mark.asyncio
    async def test_oauth_token_prefix_returns_none(self, mock_pool: MagicMock) -> None:
        result = await validate_personal_api_key("pha_oauth_token", mock_pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_key_returns_authenticated_user(self, mock_pool: MagicMock) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={"id": "k1", "user_id": 123, "scopes": ["task:write"], "current_team_id": 456}
        )

        result = await validate_personal_api_key("phx_test_key", mock_pool)

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
    async def test_invalid_keys_return_none(self, mock_pool: MagicMock, db_result: dict | None) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(return_value=db_result)

        result = await validate_personal_api_key("phx_invalid_key", mock_pool)
        assert result is None


class TestOAuthToken:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "token",
        [
            pytest.param("phx_personal_key", id="personal_api_key_prefix"),
            pytest.param("Bearer token", id="bearer_prefix"),
            pytest.param("random_token", id="no_prefix"),
        ],
    )
    async def test_non_oauth_prefix_returns_none(self, mock_pool: MagicMock, token: str) -> None:
        result = await validate_oauth_token(token, mock_pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_token_not_found_returns_none(self, mock_pool: MagicMock) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(return_value=None)

        result = await validate_oauth_token("pha_unknown_token", mock_pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self, mock_pool: MagicMock) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "task:write",
                "expires": datetime.now(UTC) - timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
            }
        )

        result = await validate_oauth_token("pha_expired_token", mock_pool)
        assert result is None

    @pytest.mark.asyncio
    async def test_token_without_expiry_is_valid(self, mock_pool: MagicMock) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "task:write",
                "expires": None,
                "current_team_id": 456,
                "application_id": 789,
            }
        )

        result = await validate_oauth_token("pha_no_expiry", mock_pool)

        assert result is not None
        assert result.user_id == 123

    @pytest.mark.asyncio
    async def test_missing_application_id_returns_none(self, mock_pool: MagicMock) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "task:write",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": None,
            }
        )

        result = await validate_oauth_token("pha_no_app_id", mock_pool)
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
    async def test_missing_task_write_scope_returns_none(self, mock_pool: MagicMock, scope: str | None) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": scope,
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
            }
        )

        result = await validate_oauth_token("pha_wrong_scope", mock_pool)
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scope,expected_scopes",
        [
            pytest.param("task:write", ["task:write"], id="single_scope"),
            pytest.param("task:write task:read", ["task:write", "task:read"], id="multiple_scopes"),
            pytest.param("read:all task:write admin", ["read:all", "task:write", "admin"], id="three_scopes"),
        ],
    )
    async def test_scope_parsing(self, mock_pool: MagicMock, scope: str, expected_scopes: list[str]) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": scope,
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
            }
        )

        result = await validate_oauth_token("pha_valid_token", mock_pool)

        assert result is not None
        assert result.scopes == expected_scopes

    @pytest.mark.asyncio
    async def test_valid_token_returns_authenticated_user(self, mock_pool: MagicMock) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "task:write",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": 456,
                "application_id": 789,
            }
        )

        result = await validate_oauth_token("pha_valid_token", mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id == 456
        assert result.auth_method == "oauth"
        assert result.scopes == ["task:write"]

    @pytest.mark.asyncio
    async def test_valid_token_with_null_team_id(self, mock_pool: MagicMock) -> None:
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(
            return_value={
                "id": 1,
                "user_id": 123,
                "scope": "task:write",
                "expires": datetime.now(UTC) + timedelta(hours=1),
                "current_team_id": None,
                "application_id": 789,
            }
        )

        result = await validate_oauth_token("pha_valid_token", mock_pool)

        assert result is not None
        assert result.user_id == 123
        assert result.team_id is None
