from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from openai import OpenAI


class FeedbackTranscriber:
    @staticmethod
    def transcribe(audio: UploadedFile) -> str:
        with OpenAI(
            api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL, timeout=30, max_retries=0
        ) as client:
            result = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=(
                    "feedback."
                    + {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg"}[audio.content_type or ""],
                    audio.read(),
                    audio.content_type,
                ),
            )
        return result.text.strip()
