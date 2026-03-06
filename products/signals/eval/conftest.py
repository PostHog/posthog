import os
import logging
from pathlib import Path

import pytest

from dotenv import load_dotenv
from posthoganalytics import Posthog
from posthoganalytics.ai.openai import AsyncOpenAI

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

logging.getLogger("google_genai").setLevel(logging.ERROR)
logging.getLogger("google.genai").setLevel(logging.ERROR)

# Gemini client expects GOOGLE_API_KEY; alias from GEMINI_API_KEY if needed
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]


def pytest_addoption(parser):
    parser.addoption("--case-ids", default=None, help="Comma-separated ticket IDs to run (e.g. 00005,00010)")


@pytest.fixture
def case_ids(request):
    raw = request.config.getoption("--case-ids")
    if raw is None:
        return None
    return {s.strip() for s in raw.split(",") if s.strip()}


@pytest.fixture
def posthog_client():
    api_key = os.environ.get("POSTHOG_PROJECT_API_KEY", "")
    host = os.environ.get("POSTHOG_HOST", "http://localhost:8010")
    client = Posthog(api_key, host=host, disabled=False)
    yield client
    client.shutdown()


@pytest.fixture
def openai_client(posthog_client):
    return AsyncOpenAI(posthog_client=posthog_client)
