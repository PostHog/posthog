from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from openai import OpenAIError
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from products.mcp_analytics.backend.feedback_audio import FeedbackTranscriber


@extend_schema_field(OpenApiTypes.BINARY)
class FeedbackAudioFileField(serializers.FileField):
    pass


class FeedbackAudioRequestSerializer(serializers.Serializer):
    audio = FeedbackAudioFileField(help_text="Recorded feedback in WebM, MP4, or Ogg format, up to 5 MiB.")

    def validate_audio(self, value: UploadedFile) -> UploadedFile:
        if value.size is None or value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Recording is too large. Record a shorter answer or type your feedback.")
        if value.content_type not in {"audio/webm", "audio/mp4", "audio/ogg"}:
            raise serializers.ValidationError("Unsupported recording format. Please type your feedback.")
        return value


class FeedbackAudioResponseSerializer(serializers.Serializer):
    text = serializers.CharField(help_text="Transcribed feedback for the respondent to review before submitting.")


class FeedbackAudioErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the recording could not be transcribed and how to continue.")


class FeedbackAudioThrottle(UserRateThrottle):
    scope = "mcp_feedback_audio"
    rate = "5/minute"


class MCPFeedbackAudioViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "mcp_analytics"
    posthog_feature_flag = "mcp-analytics-feedback-voice"
    permission_classes = [PostHogFeatureFlagPermission]
    parser_classes = [MultiPartParser]
    throttle_classes = [FeedbackAudioThrottle]
    serializer_class = FeedbackAudioRequestSerializer

    @validated_request(
        request_serializer=FeedbackAudioRequestSerializer,
        responses={
            200: FeedbackAudioResponseSerializer,
            422: FeedbackAudioErrorSerializer,
            503: FeedbackAudioErrorSerializer,
        },
        operation_id="mcp_analytics_feedback_audio_create",
        description="Transcribe a short feedback recording without storing the audio or submitting a survey response.",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        if not self.team.organization.is_ai_data_processing_approved:
            raise PermissionDenied(
                "AI data processing is not enabled for this organization. Please type your feedback."
            )
        if not settings.OPENAI_API_KEY:
            return Response({"detail": "Voice feedback is unavailable. Please type your feedback."}, status=503)
        try:
            text = FeedbackTranscriber.transcribe(request.validated_data["audio"])
        except OpenAIError:
            return Response(
                {"detail": "Couldn't transcribe your recording. Try again or type your feedback."}, status=503
            )
        if not text or len(text) > 2000:
            return Response(
                {"detail": "Couldn't use this recording. Record a shorter answer or type your feedback."}, status=422
            )
        return Response(FeedbackAudioResponseSerializer({"text": text}).data)
