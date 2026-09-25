from typing import Any, cast

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.user import User
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.client_provenance import is_sandbox_oauth_request
from products.tasks.backend.presentation.serializers import TaskRunErrorResponseSerializer


class VoiceSessionRequestSerializer(serializers.Serializer):
    sdp = serializers.CharField(max_length=32768, trim_whitespace=False, help_text="The client's WebRTC SDP offer.")
    structured_tools = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Use Responses delegation for structured desktop voice tool calls.",
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        # boffin: Keep the wire field named context without overriding DRF's serializer context.
        fields["context"] = serializers.CharField(
            max_length=8000,
            required=False,
            default="",
            allow_blank=True,
            help_text="Recent conversation text for voice context.",
        )
        return fields


class VoiceSessionResponseSerializer(serializers.Serializer):
    sdp = serializers.CharField(help_text="OpenAI's WebRTC SDP answer. Contains no project API key.")


class VoiceSessionThrottle(UserRateThrottle):
    scope = "desktop_voice"
    rate = "3/min"


class VoiceSessionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    throttle_classes = [VoiceSessionThrottle]
    scope_object = "task"
    scope_object_write_actions = ["create"]
    serializer_class = VoiceSessionRequestSerializer

    @validated_request(
        request_serializer=VoiceSessionRequestSerializer,
        responses={
            201: OpenApiResponse(response=VoiceSessionResponseSerializer),
            503: OpenApiResponse(response=TaskRunErrorResponseSerializer),
        },
        summary="Start voice for a task conversation",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        user = cast(User, request.user)
        if is_sandbox_oauth_request(request):
            raise PermissionDenied("Task agents cannot start voice sessions.")
        if not user.is_staff:
            raise PermissionDenied("Voice conversations are available to PostHog staff only.")
        if tasks_facade.get_task_detail(self.kwargs["parent_lookup_task_id"], self.team_id, user.id) is None:
            raise NotFound()
        if self.organization.is_ai_data_processing_approved is not True:
            raise PermissionDenied("Enable AI data processing before starting voice.")
        distinct_id = user.distinct_id
        try:
            enabled = distinct_id is not None and posthoganalytics.feature_enabled(
                "posthog-desktop-voice", distinct_id, send_feature_flag_events=False
            )
        except Exception:
            enabled = False
        if enabled is not True:
            raise PermissionDenied("Voice conversations are not enabled for this account.")
        try:
            result = tasks_facade.create_voice_session(
                request.validated_data["sdp"],
                request.validated_data["context"],
                structured_tools=request.validated_data["structured_tools"],
            )
        except tasks_facade.VoiceSessionUnavailable:
            return Response(
                TaskRunErrorResponseSerializer(
                    {"error": "Voice could not connect. Use the text box or try again later."}
                ).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        response = Response(VoiceSessionResponseSerializer(result).data, status=status.HTTP_201_CREATED)
        response["Cache-Control"] = "no-store"
        return response
