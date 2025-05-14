from rest_framework import serializers

from .models import UserInterview
from posthog.api.shared import UserBasicSerializer

# Imports for external services - these would be used here now

# structlog for logging according to guidelines
import structlog

logger = structlog.get_logger(__name__)


class UserInterviewSerializer(serializers.ModelSerializer):
    interviewer = UserBasicSerializer()
    audio_file = serializers.FileField(write_only=True)

    class Meta:
        model = UserInterview
        fields = ("id", "created_by", "created_at", "interviewee_emails", "transcript", "summary", "audio_file")
        read_only_fields = ("id", "created_by", "created_at", "interviewee_emails", "transcript")

    def create(self, validated_data): ...
