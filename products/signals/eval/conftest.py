import os
from pathlib import Path

import pytest

from dotenv import load_dotenv
from posthoganalytics import Posthog
from posthoganalytics.ai.openai import OpenAI

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


@pytest.fixture
def posthog_client():
    api_key = os.environ.get("POSTHOG_PROJECT_API_KEY", "")
    host = os.environ.get("POSTHOG_HOST", "http://localhost:8010")
    client = Posthog(api_key, host=host, disabled=False)
    yield client
    client.shutdown()


@pytest.fixture
def openai_client(posthog_client):
    return OpenAI(posthog_client=posthog_client)
