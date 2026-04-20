"""
Integration tests for audio transcription using the OpenAI SDK through the gateway.

Skipped unless OPENAI_API_KEY is set and audio samples exist.
Run with: pytest tests/integration/test_openai_transcription.py -v

Add audio files to tests/integration/audio_samples/ to run these tests.
"""

import os
from pathlib import Path

import pytest
from openai import NotFoundError, OpenAI

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
AUDIO_SAMPLES_DIR = Path(__file__).parent / "audio_samples"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".webm", ".mp4", ".mpeg", ".mpga", ".oga", ".ogg", ".flac"}

skip_without_openai_key = pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY not set")


@pytest.fixture
def audio_file() -> Path:
    """Get an audio file from audio_samples, skip if none exist."""
    if not AUDIO_SAMPLES_DIR.exists():
        pytest.skip("audio_samples directory not found")
    files = [f for f in AUDIO_SAMPLES_DIR.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS]
    if not files:
        pytest.skip("No audio files found in tests/integration/audio_samples/")
    return files[0]


@skip_without_openai_key
class TestOpenAIAudioTranscription:
    def test_basic_transcription(self, openai_client: OpenAI, audio_file: Path):
        with open(audio_file, "rb") as f:
            response = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )

        assert response is not None
        assert response.text is not None
        assert len(response.text) > 0

    def test_transcription_with_language_hint(self, openai_client: OpenAI, audio_file: Path):
        with open(audio_file, "rb") as f:
            response = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="en",
            )

        assert response is not None
        assert response.text is not None

    def test_transcription_with_product_route(self, gateway_url: str, audio_file: Path):
        client = OpenAI(
            api_key="phx_fake_personal_api_key",
            base_url=f"{gateway_url}/llm_gateway/v1",
        )

        with open(audio_file, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )

        assert response is not None
        assert response.text is not None

    def test_response_is_text(self, openai_client: OpenAI, audio_file: Path):
        with open(audio_file, "rb") as f:
            response = openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )

        assert isinstance(response.text, str)
        assert len(response.text.strip()) > 0

    def test_sequential_transcriptions(self, openai_client: OpenAI, audio_file: Path):
        with open(audio_file, "rb") as f:
            response1 = openai_client.audio.transcriptions.create(model="whisper-1", file=f)

        with open(audio_file, "rb") as f:
            response2 = openai_client.audio.transcriptions.create(model="whisper-1", file=f)

        assert response1.text is not None
        assert response2.text is not None

    @pytest.mark.parametrize("model", ["whisper-1", "gpt-4o-transcribe"])
    def test_transcription_models(self, openai_client: OpenAI, audio_file: Path, model: str):
        with open(audio_file, "rb") as f:
            response = openai_client.audio.transcriptions.create(
                model=model,
                file=f,
            )

        assert response is not None
        assert response.text is not None

    def test_invalid_model_rejected(self, openai_client: OpenAI, audio_file: Path):
        with open(audio_file, "rb") as f:
            with pytest.raises(NotFoundError):
                openai_client.audio.transcriptions.create(
                    model="invalid-model-name",
                    file=f,
                )
