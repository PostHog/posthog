from django.db import transaction

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
from .serializers import (
    CreateRecordingRequestSerializer,
    CreateRecordingResponseSerializer,
    DesktopRecordingSerializer,
    RecordingTranscriptSerializer,
    UploadTranscriptSerializer,
)
from .services.recall_client import RecallAIClient


@extend_schema(tags=["desktop_recordings"])
class DesktopRecordingViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    RESTful API for managing desktop meeting recordings.

    Standard CRUD operations plus transcript management as a subresource.
    """

    serializer_class = DesktopRecordingSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "desktop_recording"
    scope_object_read_actions = ["list", "retrieve", "transcript"]
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "transcript"]
    queryset = DesktopRecording.objects.all()

    def safely_get_queryset(self, queryset):
        """Filter recordings to current team"""
        queryset = queryset.filter(team=self.team).select_related("transcript")

        user_id = self.request.query_params.get("user_id")
        if user_id:
            queryset = queryset.filter(created_by_id=user_id)

        platform = self.request.query_params.get("platform")
        if platform:
            queryset = queryset.filter(platform=platform)

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(transcript__full_text__icontains=search)

        return queryset

    @extend_schema(
        request=CreateRecordingRequestSerializer,
        responses={201: CreateRecordingResponseSerializer},
        description="Create a new recording and get Recall.ai upload token for the desktop SDK",
    )
    @transaction.atomic
    def create(self, request, **kwargs):
        """
        RESTful POST /desktop_recordings/

        Create a new recording with Recall.ai upload token.
        Auto-creates empty transcript record.
        """
        from posthog.settings.integrations import RECALL_AI_API_KEY, RECALL_AI_API_URL

        if not RECALL_AI_API_KEY:
            return Response({"detail": "Recall.ai API key not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        request_serializer = CreateRecordingRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        platform = request_serializer.validated_data["platform"]

        recall_client = RecallAIClient(api_key=RECALL_AI_API_KEY, api_url=RECALL_AI_API_URL)

        try:
            upload_response = recall_client.create_sdk_upload(
                recording_config={
                    "transcript": {"provider": {"assembly_ai_v3_streaming": {}}},
                    "realtime_endpoints": [{"type": "desktop_sdk_callback", "events": ["transcript.data"]}],
                }
            )
        except Exception as e:
            return Response(
                {"detail": f"Failed to create upload with Recall.ai: {str(e)}"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        recording = DesktopRecording.objects.create(
            team=self.team,
            created_by=request.user,
            sdk_upload_id=upload_response["id"],
            status=DesktopRecording.Status.RECORDING,
            platform=platform,
        )

        RecordingTranscript.objects.create(recording=recording, full_text="", segments=[])

        serializer = self.get_serializer(recording)
        response_data = serializer.data
        response_data["upload_token"] = upload_response["upload_token"]

        return Response(response_data, status=status.HTTP_201_CREATED)

    @extend_schema(
        methods=["GET"],
        request=None,
        responses={200: RecordingTranscriptSerializer},
        description="Retrieve transcript for a recording",
    )
    @extend_schema(
        methods=["POST"],
        request=UploadTranscriptSerializer,
        responses={200: RecordingTranscriptSerializer},
        description="Upload transcript segments (supports batched real-time streaming)",
    )
    @action(detail=True, methods=["GET", "POST"])
    def transcript(self, request, pk=None, **kwargs):
        """
        RESTful transcript subresource endpoint.

        GET: Retrieve transcript data
        POST: Upload transcript segments in batches (supports real-time streaming)
        """
        recording = self.get_object()

        if request.method == "GET":
            # Transcript is always created with recording (auto-created empty in create())
            serializer = RecordingTranscriptSerializer(recording.transcript)
            return Response(serializer.data)

        serializer = UploadTranscriptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        segments = serializer.validated_data.get("segments", [])
        transcript = recording.transcript

        # Append new segments to existing ones (for batched uploads)
        existing_segments = transcript.segments or []
        existing_timestamps = {s.get("timestamp") for s in existing_segments if s.get("timestamp") is not None}

        # Only add segments with new timestamps to avoid duplicates
        # Segments with None timestamps are always added (can't deduplicate reliably)
        new_segments = [
            s for s in segments if s.get("timestamp") is None or s.get("timestamp") not in existing_timestamps
        ]

        transcript.segments = existing_segments + new_segments
        transcript.full_text = " ".join(s.get("text", "") for s in transcript.segments if s.get("text"))
        transcript.save(update_fields=["segments", "full_text", "updated_at"])

        return Response(RecordingTranscriptSerializer(transcript).data)
