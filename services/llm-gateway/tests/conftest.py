from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.model_throttles import (
    ProductModelInputTokenThrottle,
    ProductModelOutputTokenThrottle,
    UserModelInputTokenThrottle,
    UserModelOutputTokenThrottle,
)
from llm_gateway.rate_limiting.runner import ThrottleRunner


def create_test_app(mock_db_pool: MagicMock) -> FastAPI:
    from llm_gateway.api.health import health_router
    from llm_gateway.api.routes import router

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.db_pool = mock_db_pool
        app.state.redis = None
        app.state.throttle_runner = ThrottleRunner(
            throttles=[
                ProductModelInputTokenThrottle(redis=None),
                UserModelInputTokenThrottle(redis=None),
                ProductModelOutputTokenThrottle(redis=None),
                UserModelOutputTokenThrottle(redis=None),
            ]
        )
        yield

    app = FastAPI(title="LLM Gateway Test", lifespan=test_lifespan)
    app.include_router(health_router)
    app.include_router(router)
    return app


@pytest.fixture
def mock_db_pool() -> MagicMock:
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=1)
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    return pool


@pytest.fixture
def authenticated_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=1,
        team_id=1,
        auth_method="personal_api_key",
        scopes=["llm_gateway:read"],
    )


@pytest.fixture
def app(mock_db_pool: MagicMock) -> Generator[FastAPI, None, None]:
    application = create_test_app(mock_db_pool)
    yield application


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def authenticated_client(mock_db_pool: MagicMock) -> Generator[TestClient, None, None]:
    app = create_test_app(mock_db_pool)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": "key_id",
            "user_id": 1,
            "scopes": ["llm_gateway:read"],
            "current_team_id": 1,
        }
    )
    mock_db_pool.acquire = AsyncMock(return_value=conn)
    mock_db_pool.release = AsyncMock()

    with TestClient(app) as c:
        yield c
