from __future__ import annotations

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User
from posthog.permissions import TeamMemberStrictManagementPermission, TimeSensitiveActionPermission

from products.logs.backend.facade.signing_secret import (
    SigningSecretState,
    expire_previous_signing_secret,
    get_signing_secret,
    rotate_signing_secret,
)


class LogsSigningSecretSerializer(serializers.Serializer):
    secret = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Raw secret that a server uses to sign log requests (HMAC). Null until one exists.",
    )
    updated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the secret last changed, or null when no secret exists yet.",
    )
    previous_secret_valid_until = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Until when the previous secret stays valid after a rotation, or null when no grace period is active.",
    )


def _response(state: SigningSecretState) -> Response:
    return Response(
        LogsSigningSecretSerializer(
            {
                "secret": state.secret,
                "updated_at": state.updated_at,
                "previous_secret_valid_until": state.previous_secret_valid_until,
            }
        ).data
    )


class _SessionOnlyPermission(BasePermission):
    # "INTERNAL" rejects scoped tokens only. An impersonation JWT carries no session, so
    # without this check it passes the scope check and skips the session-freshness check.
    message = "The signing secret is only available in the web app."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.successful_authenticator, SessionAuthentication)


class _LogsAccessPermission(BasePermission):
    # "INTERNAL" also turns off the resource-level access check, so this class checks Logs access itself.
    message = "You don't have access to Logs in this project."

    def has_permission(self, request: Request, view: APIView) -> bool:
        level = "viewer" if request.method in SAFE_METHODS else "editor"
        return cast(Any, view).user_access_control.check_access_level_for_resource("logs", level)


class _SingletonSchema(PostHogAutoSchema):
    """A project has one signing secret, so ``list`` must not wrap the response in an array."""

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class LogsSigningSecretViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    schema = _SingletonSchema()
    # The raw secret must stay out of reach of scoped tokens, so the viewset allows session auth only.
    scope_object = "INTERNAL"
    pagination_class = None
    serializer_class = LogsSigningSecretSerializer
    permission_classes = [
        _SessionOnlyPermission,
        TimeSensitiveActionPermission,
        TeamMemberStrictManagementPermission,
        _LogsAccessPermission,
    ]

    @extend_schema(
        responses=LogsSigningSecretSerializer,
        description="The secret that servers use to sign log requests for this project.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return _response(get_signing_secret(self.team))

    @extend_schema(
        request=None,
        responses=LogsSigningSecretSerializer,
        description="Generate a new signing secret. The previous secret stays valid for 48 hours, then expires.",
    )
    @action(methods=["POST"], detail=False)
    def rotate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return _response(rotate_signing_secret(self.team, cast(User, request.user), is_impersonated(request)))

    @extend_schema(
        request=None,
        responses=LogsSigningSecretSerializer,
        description="End the grace period now, so the previous secret stops being valid immediately. Use it when the replaced secret may be compromised, or once every server uses the new one.",
    )
    @action(methods=["POST"], detail=False)
    def expire_previous(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return _response(expire_previous_signing_secret(self.team, cast(User, request.user), is_impersonated(request)))
