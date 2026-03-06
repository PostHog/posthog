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
