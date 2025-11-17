from rest_framework import serializers

from .models import DesktopRecording


class TranscriptSegmentSerializer(serializers.Serializer):
    """Serializer for individual transcript segments from AssemblyAI"""

    timestamp = serializers.FloatField(required=False, allow_null=True, help_text="Milliseconds from recording start")
    speaker = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    text = serializers.CharField(required=True, allow_blank=False)
    confidence = serializers.FloatField(required=False, allow_null=True, help_text="Transcription confidence score")
    is_final = serializers.BooleanField(required=False, allow_null=True, help_text="Whether this is the final version")


class TaskSerializer(serializers.Serializer):
    """Serializer for extracted tasks"""

    title = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    assignee = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class AppendSegmentsSerializer(serializers.Serializer):
    """Serializer for appending transcript segments (supports batched real-time uploads)"""

    segments = serializers.ListField(child=TranscriptSegmentSerializer(), required=True, min_length=1)


class DesktopRecordingSerializer(serializers.ModelSerializer):
    # Type hints for JSON fields for proper OpenAPI/TypeScript generation
    participants = serializers.ListField(
        child=serializers.CharField(), read_only=False, required=False, help_text="List of participant names"
    )

    transcript_segments = serializers.ListField(
        child=TranscriptSegmentSerializer(), required=False, help_text="Transcript segments with timestamps"
    )

    extracted_tasks = serializers.ListField(
        child=TaskSerializer(), read_only=False, required=False, help_text="AI-extracted tasks from transcript"
    )

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
            "transcript_text",
            "transcript_segments",
            "summary",
            "extracted_tasks",
            "tasks_generated_at",
            "summary_generated_at",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "team",
            "created_by",
            "sdk_upload_id",
            "created_at",
            "updated_at",
            "transcript_text",
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
