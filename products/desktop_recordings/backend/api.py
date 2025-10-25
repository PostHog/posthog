from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from .models import DesktopRecording, RecordingTranscript
from .serializers import CreateUploadResponseSerializer, DesktopRecordingSerializer, RecordingTranscriptSerializer
from .services.recall_client import RecallAIClient


@extend_schema(tags=["desktop_recordings"])
class DesktopRecordingViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing desktop meeting recordings.

    Recordings are created by the Array desktop app via the create-upload endpoint,
    then managed through standard CRUD operations.
    """

    serializer_class = DesktopRecordingSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "desktop_recording"
    scope_object_read_actions = ["list", "retrieve", "transcript"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "create_upload", "upload_transcript"]
    queryset = DesktopRecording.objects.all()

    def safely_get_queryset(self, queryset):
        """Filter recordings to current team"""
        qs = queryset.filter(team=self.team).select_related("transcript")

        # Filter by user
        user_id = self.request.query_params.get("user_id")
        if user_id:
            qs = qs.filter(created_by_id=user_id)

        # Filter by platform
        platform = self.request.query_params.get("platform")
        if platform:
            qs = qs.filter(platform=platform)

        # Filter by status
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        # Search transcript text
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(transcript__full_text__icontains=search)

        return qs

    @extend_schema(
        request=None,
        responses={200: CreateUploadResponseSerializer},
        description="Create a Recall.ai SDK upload token for the Array desktop app to start recording",
    )
    @action(detail=False, methods=["POST"])
    def create_upload(self, request, **kwargs):
        """
        Create a new recording and return Recall.ai upload token.

        Called by Array desktop app when a meeting is detected.
        """
        from posthog.settings.integrations import RECALL_AI_API_KEY, RECALL_AI_API_URL

        if not RECALL_AI_API_KEY:
            return Response({"detail": "Recall.ai API key not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        recall_client = RecallAIClient(api_key=RECALL_AI_API_KEY, api_url=RECALL_AI_API_URL)

        # Create upload with Recall.ai
        upload_response = recall_client.create_sdk_upload(
            recording_config={"transcript": {"provider": {"assembly_ai_v3_streaming": {}}}}
        )

        # Create recording in our DB
        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=request.user,
            sdk_upload_id=upload_response["id"],
            status=DesktopRecording.Status.RECORDING,
            platform=request.data.get("platform", DesktopRecording.Platform.DESKTOP_AUDIO),
        )

        return Response({"upload_token": upload_response["upload_token"], "recording_id": str(recording.id)})

    @extend_schema(
        request=None,
        responses={200: RecordingTranscriptSerializer},
        description="Get transcript and extracted tasks for a recording",
    )
    @action(detail=True, methods=["GET"])
    def transcript(self, request, pk=None, **kwargs):
        """Get transcript data for a recording"""
        recording = self.get_object()

        if not hasattr(recording, "transcript"):
            return Response({"detail": "Transcript not yet available"}, status=status.HTTP_404_NOT_FOUND)

        serializer = RecordingTranscriptSerializer(recording.transcript)
        return Response(serializer.data)

    @extend_schema(
        request=RecordingTranscriptSerializer,
        responses={200: RecordingTranscriptSerializer},
        description="Upload transcript data from Array desktop app",
    )
    @action(detail=True, methods=["POST"])
    def upload_transcript(self, request, pk=None, **kwargs):
        """
        Upload transcript data for a recording.

        Called by Array desktop app after downloading transcript from Recall.ai.
        Creates or updates the transcript and marks recording as complete.
        """
        recording = self.get_object()

        # Create or update transcript
        transcript, created = RecordingTranscript.objects.update_or_create(
            recording=recording,
            defaults={
                "full_text": request.data.get("full_text", ""),
                "segments": request.data.get("segments", []),
                "summary": request.data.get("summary"),
                "extracted_tasks": request.data.get("extracted_tasks", []),
            },
        )

        # Update recording status to complete
        recording.status = DesktopRecording.Status.COMPLETE
        recording.save(update_fields=["status", "updated_at"])

        serializer = RecordingTranscriptSerializer(transcript)
        return Response(serializer.data, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)
