from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from django.db import transaction

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User
from posthog.models.utils import generate_random_token, mask_key_value
from posthog.permissions import TeamMemberStrictManagementPermission, TimeSensitiveActionPermission

from products.logs.backend.models import LogsSigningSecret


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


def _serializer_payload(row: LogsSigningSecret | None) -> dict[str, Any]:
    return {
        "secret": row.secret if row else None,
        "updated_at": row.updated_at if row else None,
        "previous_secret_valid_until": row.previous_secret_valid_until if row and row.previous_secret_active else None,
    }


class _SessionOnlyPermission(BasePermission):
    # "INTERNAL" rejects scoped tokens only. An impersonation JWT carries no session, so
    # without this check it passes the scope check and skips the session-freshness check.
    message = "The signing secret is only available in the web app."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.successful_authenticator, SessionAuthentication)


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
    permission_classes = [_SessionOnlyPermission, TimeSensitiveActionPermission, TeamMemberStrictManagementPermission]

    def _log_change(self, request: Request, change: Change) -> None:
        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            scope="Team",
            item_id=self.team_id,
            activity="updated",
            detail=Detail(name=str(self.team.name), changes=[change]),
        )

    @extend_schema(
        responses=LogsSigningSecretSerializer,
        description="The secret that servers use to sign log requests for this project.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        row = LogsSigningSecret.objects.for_team(self.team_id).first()
        return Response(LogsSigningSecretSerializer(_serializer_payload(row)).data)

    @extend_schema(
        request=None,
        responses=LogsSigningSecretSerializer,
        description="Generate a new signing secret. The previous secret stays valid for 48 hours, then expires.",
    )
    @action(methods=["POST"], detail=False)
    def rotate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # One transaction, because a credential change must not commit without its audit row.
        with transaction.atomic():
            # The row lock makes two concurrent requests run one after the other. Without it,
            # the second request overwrites the secret that the first request just returned.
            # With it, the second request rotates the first secret into the grace period.
            row, created = (
                LogsSigningSecret.objects.for_team(self.team_id)
                .select_for_update()
                .get_or_create(team_id=self.team_id, defaults={"secret": generate_random_token()})
            )
            old_secret = None if created else row.secret
            if not created:
                row.previous_secret = row.secret
                row.previous_secret_rotated_at = datetime.now(UTC)
                row.secret = generate_random_token()
                row.save()
            self._log_change(
                request,
                Change(
                    type="Team",
                    action="created" if created else "changed",
                    field="logs_signing_secret",
                    before=mask_key_value(old_secret) if old_secret else None,
                    after=mask_key_value(row.secret),
                ),
            )
        return Response(LogsSigningSecretSerializer(_serializer_payload(row)).data)

    @extend_schema(
        request=None,
        responses=LogsSigningSecretSerializer,
        description="End the grace period now, so the previous secret stops being valid immediately. Use it when the replaced secret may be compromised, or once every server uses the new one.",
    )
    @action(methods=["POST"], detail=False)
    def expire_previous(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        with transaction.atomic():
            row = LogsSigningSecret.objects.for_team(self.team_id).select_for_update().first()
            if row and row.previous_secret:
                expired = row.previous_secret
                row.previous_secret = None
                row.previous_secret_rotated_at = None
                row.save(update_fields=["previous_secret", "previous_secret_rotated_at", "updated_at"])
                self._log_change(
                    request,
                    Change(
                        type="Team",
                        action="deleted",
                        field="logs_signing_secret_previous",
                        before=mask_key_value(expired),
                        after=None,
                    ),
                )
        return Response(LogsSigningSecretSerializer(_serializer_payload(row)).data)
