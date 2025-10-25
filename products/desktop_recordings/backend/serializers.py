from rest_framework import serializers

from .models import DesktopRecording, RecordingTranscript


class RecordingTranscriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecordingTranscript
        fields = [
            "full_text",
            "segments",
            "summary",
            "extracted_tasks",
            "tasks_generated_at",
            "summary_generated_at",
            "created_at",
            "updated_at",
        ]


class TranscriptSegmentSerializer(serializers.Serializer):
    """Serializer for individual transcript segments"""

    text = serializers.CharField(required=True, allow_blank=False)
    timestamp = serializers.FloatField(required=False, allow_null=True)
    speaker = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class UploadTranscriptSerializer(serializers.Serializer):
    """Serializer for uploading transcript segments (supports batched uploads)"""

    segments = serializers.ListField(child=TranscriptSegmentSerializer(), required=False, default=list)
    full_text = serializers.CharField(required=False, default="", allow_blank=True)


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
            "notes",
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


class CreateRecordingRequestSerializer(serializers.Serializer):
    """Request body for creating a new recording"""

    platform = serializers.ChoiceField(
        choices=["zoom", "teams", "meet", "desktop_audio", "slack"],
        default="desktop_audio",
        help_text="Meeting platform being recorded",
    )


class CreateRecordingResponseSerializer(DesktopRecordingSerializer):
    """Response for creating a new recording (includes upload_token)"""

    upload_token = serializers.CharField(help_text="Recall.ai upload token for the desktop SDK")

    class Meta(DesktopRecordingSerializer.Meta):
        fields = [*DesktopRecordingSerializer.Meta.fields, "upload_token"]
