from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_gateway.rate_limiting.redis_limiter import TokenRateLimiter


class TestTokenRateLimiter:
    @pytest.mark.parametrize(
        "tokens,limit,expected",
        [
            (50, 1000, True),  # Under fallback limit (100)
            (100, 1000, True),  # At fallback limit (100)
            (101, 1000, False),  # Over fallback limit (100)
        ],
    )
    async def test_consume_without_redis(self, tokens: int, limit: int, expected: bool) -> None:
        limiter = TokenRateLimiter(redis=None, limit=limit, window_seconds=60)
        result = await limiter.consume("test_key", tokens)
        assert result == expected

    async def test_fallback_uses_reduced_limits(self) -> None:
        limiter = TokenRateLimiter(redis=None, limit=1000, window_seconds=60)
        # Effective limit is 1000 / 10 = 100

        # First 100 tokens should be allowed
        result = await limiter.consume("key1", 100)
        assert result is True

        # Next 1 token should be denied (over fallback limit)
        result = await limiter.consume("key1", 1)
        assert result is False

    async def test_redis_consumes_tokens(self) -> None:
        mock_redis: MagicMock = MagicMock()
        mock_redis.incrby = AsyncMock(return_value=100)
        mock_redis.expire = AsyncMock()

        limiter = TokenRateLimiter(redis=mock_redis, limit=1000, window_seconds=60)

        result = await limiter.consume("test_key", 100)

        assert result is True
        mock_redis.incrby.assert_called_once_with("ratelimit:test_key", 100)

    async def test_redis_sets_expire_on_first_increment(self) -> None:
        mock_redis: MagicMock = MagicMock()
        mock_redis.incrby = AsyncMock(return_value=50)  # First increment = same as tokens
        mock_redis.expire = AsyncMock()

        limiter = TokenRateLimiter(redis=mock_redis, limit=1000, window_seconds=60)

        await limiter.consume("test_key", 50)

        mock_redis.expire.assert_called_once_with("ratelimit:test_key", 60)

    async def test_redis_error_falls_back(self) -> None:
        mock_redis: MagicMock = MagicMock()
        mock_redis.incrby = AsyncMock(side_effect=Exception("Redis connection error"))

        limiter = TokenRateLimiter(redis=mock_redis, limit=1000, window_seconds=60)

        # Should fall back to local limiter (limit/10 = 100)
        result = await limiter.consume("test_key", 50)
        assert result is True

    async def test_release_returns_tokens_redis(self) -> None:
        mock_redis: MagicMock = MagicMock()
        mock_redis.eval = AsyncMock(return_value=50)

        limiter = TokenRateLimiter(redis=mock_redis, limit=1000, window_seconds=60)

        await limiter.release("test_key", 50)

        mock_redis.eval.assert_called_once()
        call_args = mock_redis.eval.call_args
        assert "ratelimit:test_key" in call_args[0]
        assert 50 in call_args[0]

    async def test_release_falls_back_on_redis_error(self) -> None:
        mock_redis: MagicMock = MagicMock()
        mock_redis.eval = AsyncMock(side_effect=Exception("Redis error"))

        limiter = TokenRateLimiter(redis=mock_redis, limit=1000, window_seconds=60)

        # Should not raise, falls back to local
        await limiter.release("test_key", 50)

    async def test_get_remaining_without_redis(self) -> None:
        limiter = TokenRateLimiter(redis=None, limit=1000, window_seconds=60)

        # Before any consumption, should have fallback capacity (100)
        remaining = await limiter.get_remaining("test_key")
        assert remaining == 100  # 1000 / 10

    async def test_get_remaining_with_redis(self) -> None:
        mock_redis: MagicMock = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"200")

        limiter = TokenRateLimiter(redis=mock_redis, limit=1000, window_seconds=60)

        remaining = await limiter.get_remaining("test_key")
        assert remaining == 800  # 1000 - 200

    async def test_would_allow_without_redis(self) -> None:
        limiter = TokenRateLimiter(redis=None, limit=1000, window_seconds=60)
        # Fallback limit is 100

        # Should allow 50 tokens
        assert await limiter.would_allow("test_key", 50) is True
        # Should allow 100 tokens (at limit)
        assert await limiter.would_allow("test_key", 100) is True
        # Should deny 101 tokens (over limit)
        assert await limiter.would_allow("test_key", 101) is False

    async def test_would_allow_does_not_consume(self) -> None:
        limiter = TokenRateLimiter(redis=None, limit=1000, window_seconds=60)
        # Fallback limit is 100

        # Check multiple times - should always allow since we're not consuming
        assert await limiter.would_allow("test_key", 100) is True
        assert await limiter.would_allow("test_key", 100) is True
        assert await limiter.would_allow("test_key", 100) is True

        # Now actually consume
        await limiter.consume("test_key", 100)

        # Should now deny
        assert await limiter.would_allow("test_key", 1) is False

    async def test_would_allow_with_redis(self) -> None:
        mock_redis: MagicMock = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"800")

        limiter = TokenRateLimiter(redis=mock_redis, limit=1000, window_seconds=60)

        # 800 used, 200 remaining - should allow 200
        assert await limiter.would_allow("test_key", 200) is True
        # Should deny 201
        assert await limiter.would_allow("test_key", 201) is False
