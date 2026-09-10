import uuid
from typing import Any, cast

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser, ScopedServiceJWTAuthentication
from posthog.redis import get_client
from posthog.tasks.push_notifications import send_user_push

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.workflows.backend.models import HogFlow
from products.workflows.backend.service_jwt import WORKFLOW_NOTIFY_PURPOSE

logger = structlog.get_logger(__name__)

PUSH_TITLE = "PostHog Desktop"

# Outlives the 30 minute token the staged fetch retries with, so a late engine retry cannot
# push the same notification twice.
IDEMPOTENCY_KEY_TTL_SECONDS = 60 * 60


class WorkflowNotificationsJWTAuthentication(ScopedServiceJWTAuthentication):
    purpose = WORKFLOW_NOTIFY_PURPOSE

    # nosemgrep: tuple-return-prefer-dataclass -- DRF's (user, auth) authentication contract
    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        user, _ = super()._authenticate_claims(request, claims)
        # The workflow is identified by the verified token, never by the request body, so a
        # token minted for one workflow can't notify another workflow's owner.
        try:
            hog_flow_id = uuid.UUID(str(claims.get("hog_flow_id")))
        except ValueError:
            raise AuthenticationFailed("Service token is missing its workflow claim.")
        return user, hog_flow_id


class WorkflowNotificationCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=100, help_text="Notification title.")
    body = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="", help_text="Notification body."
    )
    task_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Task the notification opens when tapped."
    )
    idempotency_key = serializers.CharField(
        max_length=128,
        required=False,
        help_text="Stable key for this invocation. A retried request with the same key sends nothing.",
    )


class WorkflowNotificationRejectedSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the notification was not sent.")


class WorkflowNotificationViewSet(viewsets.GenericViewSet):
    """Notify a workflow's owner from its "Notify owner" action: an in-app notification plus a
    push to the owner's devices. Authenticated by a scoped service JWT minted by the plugin
    server, never by a user credential, with its own signing key and audience."""

    authentication_classes = [WorkflowNotificationsJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowNotificationCreateSerializer

    @extend_schema(
        request=WorkflowNotificationCreateSerializer,
        responses={
            202: OpenApiResponse(description="The notification was sent, or this key already sent it"),
            422: OpenApiResponse(
                response=WorkflowNotificationRejectedSerializer,
                description="The workflow no longer exists or has no owner",
            ),
        },
        summary="Notify the workflow owner",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Both from the verified token, not the URL or body.
        user = cast(InternalAPIUser, request.user)
        team_id = cast(int, user.current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)

        serializer = WorkflowNotificationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        hog_flow = HogFlow.objects.filter(team_id=team_id, id=hog_flow_id).only("created_by_id").first()
        if hog_flow is None or hog_flow.created_by_id is None:
            return Response(
                WorkflowNotificationRejectedSerializer({"detail": "Workflow has no owner to notify."}).data,
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        idempotency_key = data.get("idempotency_key")
        dedupe_key = f"workflow_notify:{hog_flow_id}:{idempotency_key}" if idempotency_key else None
        if dedupe_key is not None and not get_client().set(dedupe_key, "1", nx=True, ex=IDEMPOTENCY_KEY_TTL_SECONDS):
            return Response(status=status.HTTP_202_ACCEPTED)

        task_id = str(data["task_id"]) if data.get("task_id") else None
        create_notification(
            NotificationData(
                team_id=team_id,
                notification_type=NotificationType.REMINDER,
                title=data["title"],
                body=data["body"],
                target_type=TargetType.USER,
                target_id=str(hog_flow.created_by_id),
                resource_type="task" if task_id else "hog_flow",
                resource_id=task_id or str(hog_flow_id),
                idempotency_key=dedupe_key,
            )
        )
        push_data: dict[str, Any] = {"hogFlowId": str(hog_flow_id)}
        if task_id:
            push_data["taskId"] = task_id
        send_user_push.delay(hog_flow.created_by_id, PUSH_TITLE, data["title"], push_data)
        return Response(status=status.HTTP_202_ACCEPTED)
