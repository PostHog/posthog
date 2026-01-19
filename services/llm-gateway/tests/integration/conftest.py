"""Shared fixtures for integration tests."""

import os
import socket
import threading
import time
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn
from anthropic import Anthropic
from openai import OpenAI

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

TEST_POSTHOG_API_KEY = "phx_fake_personal_api_key"


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
def run_gateway_server():
    mock_db_pool = create_mock_db_pool()
    port = get_free_port()

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


@pytest.fixture
def gateway_url():
    with run_gateway_server() as url:
        yield url


@pytest.fixture
def openai_client(gateway_url):
    return OpenAI(
        api_key=TEST_POSTHOG_API_KEY,
        base_url=f"{gateway_url}/v1",
    )


@pytest.fixture
def anthropic_client(gateway_url):
    return Anthropic(
        api_key=TEST_POSTHOG_API_KEY,
        base_url=gateway_url,
    )
