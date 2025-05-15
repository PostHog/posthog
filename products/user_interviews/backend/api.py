from rest_framework import viewsets
from rest_framework.parsers import MultiPartParser

from posthog.api.routing import TeamAndOrgViewSetMixin
from .models import UserInterview
from elevenlabs import ElevenLabs
import posthoganalytics
from rest_framework import serializers
from django.core.files import File
from posthog.api.shared import UserBasicSerializer
from posthoganalytics.ai.openai import OpenAI


elevenlabs_client = ElevenLabs()


class UserInterviewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    audio = serializers.FileField(write_only=True)

    class Meta:
        model = UserInterview
        fields = (
            "id",
            "created_by",
            "created_at",
            "interviewee_emails",
            "transcript",
            "summary",
            "audio",
        )
        read_only_fields = ("id", "created_by", "created_at", "transcript")

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        audio = validated_data.pop("audio")
        validated_data["transcript"] = self._transcribe_audio(audio)
        validated_data["summary"] = self._summarize_transcript(validated_data["transcript"])
        return super().create(validated_data)

    def _transcribe_audio(self, audio: File):
        transcript = elevenlabs_client.speech_to_text.convert(model_id="scribe_v1", diarize=True, file=audio)
        return transcript.text

    def _summarize_transcript(self, transcript: str):
        summary_response = OpenAI(posthog_client=posthoganalytics).responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": """
You are an expert product manager, and your sole task is to summarizes user interviews ran by our team.
""".strip(),
                },
                {
                    "role": "user",
                    "content": f"""
I interviewed a user to gather insights about our product. The goal is to capture the customer's feedback, experiences, and suggestions in a detailed and organized manner.
The notes should be comprehensive but focused, allowing for the detailed documentation of both qualitative insights and actionable items.
Pull out direct quotes and figures whenever relevant.

Because no better transcript is available, you should still do your best to summarize the interview.

<summary_format>
## User background

Capture relevant details about the user, including their role, experience, and how they interact with your product or service.
Note down here any existing solutions or workarounds they use.

## Current product usage

Document how the user is currently using the product, including frequency of use, key features used, and any specific use cases.

## Positive feedback and pain points

Summarize the positive feedback the user provided, as well as any pain points or challenges they are experiencing with the product.

## Impact of the product

Record the impact the product has had on the user's work or life, including any improvements or changes it has enabled.

## Next steps and follow-up

Record the agreed-upon next steps, including any additional actions that need to be taken, follow-up tasks, and who is responsible for them.
</summary_format>

<transcript>
{transcript}
</transcript>
""".strip(),
                },
            ],
        )
        return summary_response.output_text


class UserInterviewViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "user_interview"
    queryset = UserInterview.objects.order_by("-created_at").select_related("created_by").all()
    serializer_class = UserInterviewSerializer
    parser_classes = [MultiPartParser]
