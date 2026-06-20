from typing import cast

import structlog
from drf_spectacular.utils import OpenApiResponse
from loginas.utils import is_impersonated_session
from rest_framework import mixins, request, response, serializers, status, viewsets
from rest_framework.exceptions import APIException

from posthog.api.documentation import extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User
from posthog.permissions import IsStaffUser

from products.replay.backend.models.exported_recording import ExportedRecording
from products.replay.backend.services.export_recording import trigger_recording_export

logger = structlog.get_logger(__name__)


class ExportTriggerFailed(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to start the export workflow; please retry."
    default_code = "export_trigger_failed"


class ExportedRecordingSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, help_text="The user who triggered the export.")
    is_expired = serializers.BooleanField(
        read_only=True,
        help_text="True when the export is older than 7 days and its downloadable data may have been purged.",
    )

    class Meta:
        model = ExportedRecording
        fields = [
            "id",
            "session_id",
            "reason",
            "status",
            "export_location",
            "error_message",
            "created_at",
            "created_by",
            "is_expired",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Unique identifier for this export job."},
            "session_id": {"help_text": "The `$session_id` of the recording being exported."},
            "reason": {"help_text": "Human-provided justification for the export, kept for audit purposes."},
            "status": {"help_text": "Lifecycle status of the export: pending, running, complete, or failed."},
            "export_location": {
                "help_text": "Storage location of the exported data once the job completes; null until status is complete."
            },
            "error_message": {"help_text": "Failure detail when status is failed; null otherwise."},
            "created_at": {"help_text": "When the export was requested."},
        }


class ExportedRecordingCreateSerializer(serializers.Serializer):
    session_id = serializers.CharField(
        max_length=200,
        help_text="The `$session_id` of the recording to export.",
    )
    reason = serializers.CharField(
        help_text="Why this recording is being exported. Recorded for audit purposes.",
    )


@extend_schema(tags=["replay"])
class SessionRecordingExportViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "session_recording"
    permission_classes = [IsStaffUser]
    queryset = ExportedRecording.objects.all().select_related("created_by")
    serializer_class = ExportedRecordingSerializer

    @extend_schema(
        request=ExportedRecordingCreateSerializer,
        responses={
            201: ExportedRecordingSerializer,
            502: OpenApiResponse(description="The export was recorded but the export workflow failed to start."),
        },
        summary="Trigger a session recording export",
    )
    def create(self, request: request.Request, *args: object, **kwargs: object) -> response.Response:
        create_serializer = ExportedRecordingCreateSerializer(data=request.data)
        create_serializer.is_valid(raise_exception=True)

        try:
            export_record = trigger_recording_export(
                team=self.team,
                session_id=create_serializer.validated_data["session_id"],
                reason=create_serializer.validated_data["reason"],
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
            )
        except Exception:
            logger.exception("session_recording_export_trigger_failed", team_id=self.team.id)
            raise ExportTriggerFailed

        output = ExportedRecordingSerializer(export_record, context=self.get_serializer_context())
        return response.Response(output.data, status=status.HTTP_201_CREATED)
