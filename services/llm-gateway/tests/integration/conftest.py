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
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
FIREWORKS_API_KEY = os.environ.get("FIREWORKS_API_KEY")
CLOUDFLARE_API_KEY = os.environ.get("CLOUDFLARE_API_KEY")
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
BEDROCK_REGION = (
    os.environ.get("LLM_GATEWAY_BEDROCK_REGION_NAME")
    or os.environ.get("AWS_REGION")
    or os.environ.get("AWS_DEFAULT_REGION")
)
TEST_POSTHOG_API_KEY = "phx_fake_personal_api_key"

# Cloudflare Workers AI runs serverless and is slow + high-variance (cold starts on a large model
# can push a single completion past 3 minutes). Bound each CF call and disable SDK-level retries so
# a slow response can't blow the integration suite's CI time budget. The clients that talk to other
# providers keep the SDK defaults.
CLOUDFLARE_REQUEST_TIMEOUT = 120.0
CLOUDFLARE_MAX_RETRIES = 0

# The CF-hosted models the gateway prices and allowlists (see COST_ALIASES). Smoke-tested end-to-end
# so a routing/pricing regression for any one model fails CI rather than surfacing only in prod.
CLOUDFLARE_SMOKE_MODELS = ["@cf/moonshotai/kimi-k2.6", "@cf/zai-org/glm-5.2"]

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
    "openrouter/anthropic/claude-3.5-sonnet": {
        "litellm_provider": "openrouter",
        "max_input_tokens": 200000,
        "supports_vision": True,
        "mode": "chat",
        "input_cost_per_token": 0.000003,
        "output_cost_per_token": 0.000015,
    },
    "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct": {
        "litellm_provider": "fireworks_ai",
        "max_input_tokens": 131072,
        "supports_vision": False,
        "mode": "chat",
        "input_cost_per_token": 0.0000009,
        "output_cost_per_token": 0.0000009,
    },
    "openrouter/meta-llama/llama-3.1-8b-instruct": {
        "litellm_provider": "openrouter",
        "max_input_tokens": 131072,
        "supports_vision": False,
        "mode": "chat",
        "input_cost_per_token": 0.00000006,
        "output_cost_per_token": 0.00000006,
    },
    "fireworks_ai/accounts/fireworks/models/llama-v3p1-8b-instruct": {
        "litellm_provider": "fireworks_ai",
        "max_input_tokens": 131072,
        "supports_vision": False,
        "mode": "chat",
        "input_cost_per_token": 0.0000002,
        "output_cost_per_token": 0.0000002,
    },
    "openai/@cf/moonshotai/kimi-k2.6": {
        "litellm_provider": "openai",
        "max_input_tokens": 262144,
        "supports_vision": True,
        "supports_function_calling": True,
        "mode": "chat",
        "input_cost_per_token": 0.00000095,
        "output_cost_per_token": 0.000004,
    },
    "openai/@cf/zai-org/glm-5.2": {
        "litellm_provider": "openai",
        "max_input_tokens": 262144,
        "supports_function_calling": True,
        "mode": "chat",
        "input_cost_per_token": 0.0000014,
        "output_cost_per_token": 0.0000044,
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
            "is_staff": False,
        }
    )
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    pool.get_idle_size.return_value = 5
    pool.get_size.return_value = 10
    return pool


@contextmanager
def run_gateway_server(configure_all_providers: bool = False, bedrock_region_name: str | None = None):
    from llm_gateway.config import get_settings
    from llm_gateway.rate_limiting.model_cost_service import ModelCostService
    from llm_gateway.services.model_registry import ModelRegistryService

    mock_db_pool = create_mock_db_pool()
    port = get_free_port()

    env_patches = {}
    if bedrock_region_name:
        env_patches["LLM_GATEWAY_BEDROCK_REGION_NAME"] = bedrock_region_name
    if configure_all_providers:
        # Set both prefixed (for settings) and unprefixed (for direct env check) keys
        env_patches["LLM_GATEWAY_OPENAI_API_KEY"] = "sk-test-fake-key"
        env_patches["LLM_GATEWAY_ANTHROPIC_API_KEY"] = "sk-ant-test-fake-key"
        env_patches["LLM_GATEWAY_OPENROUTER_API_KEY"] = "or-test-fake-key"
        env_patches["LLM_GATEWAY_FIREWORKS_API_KEY"] = "fw-test-fake-key"
        env_patches["OPENAI_API_KEY"] = "sk-test-fake-key"
        env_patches["ANTHROPIC_API_KEY"] = "sk-ant-test-fake-key"
        env_patches["OPENROUTER_API_KEY"] = "or-test-fake-key"
        env_patches["FIREWORKS_API_KEY"] = "fw-test-fake-key"
    # Only LLM_GATEWAY_-prefixed vars are needed — Pydantic Settings reads them into
    # `settings.cloudflare_*`. Raw CLOUDFLARE_* vars aren't exported: the CF path injects creds
    # per-call, and exporting them would let litellm's native `cloudflare/...` provider pick them up.
    if CLOUDFLARE_API_KEY:
        env_patches["LLM_GATEWAY_CLOUDFLARE_API_KEY"] = CLOUDFLARE_API_KEY
    if CLOUDFLARE_ACCOUNT_ID:
        env_patches["LLM_GATEWAY_CLOUDFLARE_ACCOUNT_ID"] = CLOUDFLARE_ACCOUNT_ID

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


@pytest.fixture
def bedrock_gateway_url():
    with run_gateway_server(bedrock_region_name=BEDROCK_REGION) as url:
        yield url


@pytest.fixture
def bedrock_anthropic_client(bedrock_gateway_url):
    return Anthropic(
        api_key=TEST_POSTHOG_API_KEY,
        base_url=bedrock_gateway_url,
        default_headers={"X-PostHog-Provider": "bedrock"},
    )


@pytest.fixture
def cloudflare_gateway_url():
    with run_gateway_server() as url:
        yield url


@pytest.fixture
def cloudflare_anthropic_client(cloudflare_gateway_url):
    return Anthropic(
        api_key=TEST_POSTHOG_API_KEY,
        base_url=cloudflare_gateway_url,
        default_headers={"X-PostHog-Provider": "cloudflare"},
        timeout=CLOUDFLARE_REQUEST_TIMEOUT,
        max_retries=CLOUDFLARE_MAX_RETRIES,
    )


@pytest.fixture
def cloudflare_openai_client(cloudflare_gateway_url):
    return OpenAI(
        api_key=TEST_POSTHOG_API_KEY,
        base_url=f"{cloudflare_gateway_url}/v1",
        timeout=CLOUDFLARE_REQUEST_TIMEOUT,
        max_retries=CLOUDFLARE_MAX_RETRIES,
    )
