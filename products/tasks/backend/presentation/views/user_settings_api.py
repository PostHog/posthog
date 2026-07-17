from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.serializers import (
    CodeUserNotificationSettingsSerializer,
    CodeUserNotificationSettingsWriteSerializer,
)


class CodeUserSettingsViewSet(viewsets.ViewSet):
    """
    API for the requester's PostHog Code notification settings — a singleton per
    user (all-defaults when the user never saved any). User-scoped, not
    team-scoped: the settings follow the user across projects.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "user"
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(
        responses={200: CodeUserNotificationSettingsSerializer},
        summary="Get the requester's PostHog Code notification settings",
        description="Defaults (everything off) when the requester never saved settings.",
    )
    def list(self, request, **kwargs):
        settings_dto = tasks_facade.get_code_user_notification_settings(request.user.id)
        return Response(CodeUserNotificationSettingsSerializer(settings_dto).data)

    @extend_schema(
        request=CodeUserNotificationSettingsWriteSerializer,
        responses={200: CodeUserNotificationSettingsSerializer},
        summary="Update the requester's PostHog Code notification settings",
    )
    def create(self, request, **kwargs):
        serializer = CodeUserNotificationSettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings_dto = tasks_facade.update_code_user_notification_settings(
            request.user.id,
            slack_mention_notifications=serializer.validated_data["slack_mention_notifications"],
        )
        return Response(CodeUserNotificationSettingsSerializer(settings_dto).data)
