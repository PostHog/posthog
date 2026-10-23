from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser
from posthog.models import Team
from posthog.models.integration import Integration

from products.workflows.backend.facade.service_jwt import WORKFLOW_SLACK_DM_TEAM_MEMBER_PURPOSE
from products.workflows.backend.presentation.views.workflow_step_auth import WorkflowStepJWTAuthentication
from products.workflows.backend.services.slack_team_member_dm import (
    TeamMemberSlackDm,
    TeamMemberSlackDmInFlight,
    TeamMemberSlackDmOutcome,
    TeamMemberSlackDmUndeliverable,
    is_valid_button_url,
    send_team_member_slack_dm,
)


class WorkflowSlackTeamMemberMessageJWTAuthentication(WorkflowStepJWTAuthentication):
    purpose = WORKFLOW_SLACK_DM_TEAM_MEMBER_PURPOSE


class WorkflowSlackTeamMemberMessageRequestSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        min_value=1, help_text="ID of this project's Slack integration to send the message through."
    )
    recipient = serializers.CharField(
        max_length=320,
        allow_blank=True,
        help_text="Email address or PostHog user ID of the team member. Blank skips the step without a message.",
    )
    text = serializers.CharField(
        max_length=3000,
        help_text="Message text in Slack mrkdwn. Slack allows 3000 characters in one section.",
    )
    button_url = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        default="",
        help_text="Link that a button below the message opens. It must start with http:// or https://. Blank adds no button.",
    )
    button_text = serializers.CharField(
        max_length=75,
        required=False,
        allow_blank=True,
        default="",
        help_text="Label of the button. Slack allows 75 characters.",
    )
    idempotency_key = serializers.CharField(
        max_length=500, help_text="Stable identity of this workflow step execution."
    )

    def validate_button_url(self, value: str) -> str:
        if value and not is_valid_button_url(value):
            raise serializers.ValidationError("The button link must start with http:// or https://.")
        return value


class WorkflowSlackTeamMemberMessageResponseSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(
        choices=TeamMemberSlackDmOutcome.choices,
        required=False,
        help_text="`sent` when the team member got the message, `skipped` when the recipient was blank.",
    )
    detail = serializers.CharField(help_text="A short result message for the workflow log.")
    slack_user_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Slack member id that got the message. Null when nothing was sent.",
    )


class WorkflowSlackTeamMemberMessageViewSet(viewsets.GenericViewSet):
    """Send a Slack direct message to a PostHog team member, for the workflow's "Message team member on Slack" step.

    Authenticated by a scoped service JWT the plugin server mints, never by a user credential. The recipient
    comes from a workflow variable, so the send only goes to an active organization member who can access
    this project."""

    authentication_classes = [WorkflowSlackTeamMemberMessageJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowSlackTeamMemberMessageRequestSerializer

    @extend_schema(
        request=WorkflowSlackTeamMemberMessageRequestSerializer,
        responses={
            200: WorkflowSlackTeamMemberMessageResponseSerializer,
            404: OpenApiResponse(
                response=WorkflowSlackTeamMemberMessageResponseSerializer,
                description="The Slack integration doesn't exist in this project",
            ),
            409: OpenApiResponse(
                response=WorkflowSlackTeamMemberMessageResponseSerializer,
                description="Another attempt of this step is still sending. The caller retries.",
            ),
            422: OpenApiResponse(
                response=WorkflowSlackTeamMemberMessageResponseSerializer,
                description="The message can't reach the recipient",
            ),
        },
        summary="Send a workflow Slack message to a team member",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # The team comes from the verified token, not the URL or body.
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)

        serializer = WorkflowSlackTeamMemberMessageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        team = Team.objects.filter(id=team_id).first()
        integration = Integration.objects.filter(
            id=data["integration_id"], team_id=team_id, kind=Integration.IntegrationKind.SLACK
        ).first()
        if team is None or integration is None:
            return _respond(
                "The Slack workspace connection no longer exists. Select a connected Slack workspace.",
                status.HTTP_404_NOT_FOUND,
            )

        try:
            result = send_team_member_slack_dm(
                team=team,
                integration=integration,
                message=TeamMemberSlackDm(
                    recipient=data["recipient"],
                    text=data["text"],
                    button_url=data["button_url"],
                    button_text=data["button_text"],
                ),
                idempotency_key=data["idempotency_key"],
            )
        except TeamMemberSlackDmInFlight:
            return _respond("This Slack message is already being sent. Trying again.", status.HTTP_409_CONFLICT)
        except TeamMemberSlackDmUndeliverable as exc:
            return _respond(str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(WorkflowSlackTeamMemberMessageResponseSerializer(result).data)


def _respond(detail: str, http_status: int) -> Response:
    return Response(WorkflowSlackTeamMemberMessageResponseSerializer({"detail": detail}).data, status=http_status)
