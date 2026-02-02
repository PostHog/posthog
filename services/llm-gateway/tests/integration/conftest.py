"""Shared fixtures for integration tests."""

import os
import socket
import threading
import time
from contextlib import contextmanager
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn
from anthropic import Anthropic
from openai import OpenAI

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

TEST_POSTHOG_API_KEY = "phx_fake_personal_api_key"

MOCK_MODEL_COSTS = {
    "gpt-4o": {
        "litellm_provider": "openai",
        "max_input_tokens": 128000,
        "supports_vision": True,
        "mode": "chat",
        "input_cost_per_token": 0.000005,
        "output_cost_per_token": 0.000015,
    },
    "gpt-4o-mini": {
        "litellm_provider": "openai",
        "max_input_tokens": 128000,
        "supports_vision": True,
        "mode": "chat",
        "input_cost_per_token": 0.00000015,
        "output_cost_per_token": 0.0000006,
    },
    "claude-3-5-sonnet-20241022": {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
        "input_cost_per_token": 0.000003,
        "output_cost_per_token": 0.000015,
    },
    "gemini-2.0-flash": {
        "litellm_provider": "vertex_ai",
        "max_input_tokens": 1048576,
        "supports_vision": True,
        "mode": "chat",
        "input_cost_per_token": 0.000000075,
        "output_cost_per_token": 0.0000003,
    },
}


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def create_mock_db_pool():
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "id": 1,
            "user_id": 123,
            "current_team_id": 456,
            "scopes": ["llm_gateway:read"],
            "distinct_id": "test-distinct-id",
        }
    )
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    pool.get_idle_size.return_value = 5
    pool.get_size.return_value = 10
    return pool


@contextmanager
def run_gateway_server(configure_all_providers: bool = False):
    from llm_gateway.config import get_settings
    from llm_gateway.rate_limiting.model_cost_service import ModelCostService
    from llm_gateway.services.model_registry import ModelRegistryService

    mock_db_pool = create_mock_db_pool()
    port = get_free_port()

    env_patches = {}
    if configure_all_providers:
        # Set both prefixed (for settings) and unprefixed (for direct env check) keys
        env_patches["LLM_GATEWAY_OPENAI_API_KEY"] = "sk-test-fake-key"
        env_patches["LLM_GATEWAY_ANTHROPIC_API_KEY"] = "sk-ant-test-fake-key"
        env_patches["LLM_GATEWAY_GEMINI_API_KEY"] = "gemini-test-fake-key"
        env_patches["OPENAI_API_KEY"] = "sk-test-fake-key"
        env_patches["ANTHROPIC_API_KEY"] = "sk-ant-test-fake-key"
        env_patches["GEMINI_API_KEY"] = "gemini-test-fake-key"

    with patch.dict(os.environ, env_patches):
        get_settings.cache_clear()
        ModelRegistryService.reset_instance()
        ModelCostService.reset_instance()

        # Pre-populate the ModelCostService cache to avoid network calls in CI
        cost_service = ModelCostService.get_instance()
        cost_service._costs = cast(dict, MOCK_MODEL_COSTS)
        cost_service._last_refresh = time.monotonic()

        with patch("llm_gateway.main.init_db_pool", return_value=mock_db_pool):
            with patch("llm_gateway.main.close_db_pool", return_value=None):
                from llm_gateway.main import create_app

                app = create_app()
                app.state.db_pool = mock_db_pool

                config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
                server = uvicorn.Server(config)

                thread = threading.Thread(target=server.run, daemon=True)
                thread.start()

                time.sleep(0.5)

                try:
                    yield f"http://127.0.0.1:{port}"
                finally:
                    server.should_exit = True
                    thread.join(timeout=2)
                    get_settings.cache_clear()
                    ModelRegistryService.reset_instance()
                    ModelCostService.reset_instance()


@pytest.fixture
def gateway_url():
    with run_gateway_server() as url:
        yield url


@pytest.fixture
def gateway_url_all_providers():
    """Gateway URL with all providers configured (for models endpoint tests)."""
    with run_gateway_server(configure_all_providers=True) as url:
        yield url


@pytest.fixture
def openai_client(gateway_url):
    return OpenAI(
        api_key=TEST_POSTHOG_API_KEY,
        base_url=f"{gateway_url}/v1",
    )


@pytest.fixture
def openai_client_all_providers(gateway_url_all_providers):
    """OpenAI client with all providers configured (for models endpoint tests)."""
    return OpenAI(
        api_key=TEST_POSTHOG_API_KEY,
        base_url=f"{gateway_url_all_providers}/v1",
    )


@pytest.fixture
def anthropic_client(gateway_url):
    return Anthropic(
        api_key=TEST_POSTHOG_API_KEY,
        base_url=gateway_url,
    )
