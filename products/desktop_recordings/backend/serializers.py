from rest_framework import serializers

from .models import DesktopRecording, RecordingTranscript


class RecordingTranscriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecordingTranscript
        fields = ["full_text", "segments", "summary", "extracted_tasks", "created_at", "updated_at"]


class DesktopRecordingSerializer(serializers.ModelSerializer):
    transcript = RecordingTranscriptSerializer(read_only=True)

    class Meta:
        model = DesktopRecording
        fields = [
            "id",
            "team",
            "created_by",
            "sdk_upload_id",
            "recall_recording_id",
            "platform",
            "meeting_title",
            "meeting_url",
            "duration_seconds",
            "status",
            "error_message",
            "video_url",
            "video_size_bytes",
            "participants",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
            "transcript",
        ]
        read_only_fields = [
            "id",
            "team",
            "created_by",
            "sdk_upload_id",
            "created_at",
            "updated_at",
            "transcript",
        ]


class CreateUploadResponseSerializer(serializers.Serializer):
    upload_token = serializers.CharField(help_text="Recall.ai upload token for the desktop SDK")
    recording_id = serializers.UUIDField(help_text="PostHog recording ID")
