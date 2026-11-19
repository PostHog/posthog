from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.scopes.catalog import APIScopeObject

from products.messaging.backend.facade.contracts import EmailDeliveryStatus, WorkflowEmailSend
from products.messaging.backend.facade.transactional_email_log import ACTIVITY_WINDOW_DAYS
from products.messaging.backend.facade.workflow_email_log import (
    DEFAULT_LIST_DAYS,
    get_workflow_email,
    get_workflow_email_activity,
    list_workflow_emails,
)
from products.messaging.backend.presentation.query_concurrency import query_concurrency_slots
from products.messaging.backend.presentation.views.transactional_email_log import (
    TransactionalEmailActivitySerializer,
    TransactionalEmailLogEventSerializer,
    _PageSchema,
)
from products.workflows.backend.facade.api import get_workflow_view_access
from products.workflows.backend.facade.contracts import WorkflowViewAccess

FEATURE_FLAG = "workflows-email-activity"
ENGAGEMENT_NOTE = (
    "Sends are read from the workflow's run logs. The subject, the recipient's person, delivery, opens and clicks "
    "come from the `$workflows_email_*` events, which are only recorded while the project's engagement events "
    "setting is on."
)
INVOCATION_PARAMETER = OpenApiParameter(
    name="id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="The workflow run that sent the email, the `invocation_id` of a send.",
)


class WorkflowEmailListQuerySerializer(serializers.Serializer):
    workflow_id = serializers.UUIDField(help_text="The workflow or broadcast whose sends to list.")
    date_from = serializers.DateTimeField(
        required=False, help_text=f"Only sends at or after this time. Defaults to {DEFAULT_LIST_DAYS} days ago."
    )
    date_to = serializers.DateTimeField(required=False, help_text="Only sends before this time. Defaults to now.")
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200, help_text="Page size.")
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Sends to skip.")


class WorkflowEmailSendQuerySerializer(serializers.Serializer):
    action_id = serializers.CharField(
        max_length=200, help_text="The email step that sent the email, the `action_id` of a send."
    )


class WorkflowEmailSendSerializer(serializers.Serializer):
    invocation_id = serializers.CharField(help_text="The workflow run that sent the email.")
    action_id = serializers.CharField(help_text="The email step that sent it. A run can send one email per step.")
    workflow_id = serializers.CharField(help_text="The workflow or broadcast that sent the email.")
    distinct_id = serializers.CharField(
        allow_blank=True,
        help_text="The distinct ID of the person the email went to. Empty when no engagement event names it.",
    )
    recipient = serializers.CharField(help_text="The address the email was sent to.")
    subject = serializers.CharField(
        allow_blank=True,
        help_text="The subject the email went out with. Empty for a sensitive template or when no engagement event "
        "names it.",
    )
    sent_at = serializers.DateTimeField(help_text="When the email went to the provider.")
    status = serializers.ChoiceField(
        choices=EmailDeliveryStatus.choices,
        help_text="The email's delivery status. `sent` reached the email provider, `delivered` was accepted by the "
        "recipient's mail server, and `bounced` came back later.",
    )
    opened = serializers.BooleanField(help_text="Whether the recipient opened the email in the week after the send.")
    clicked = serializers.BooleanField(
        help_text="Whether the recipient clicked a link in the email in the week after the send."
    )


class WorkflowEmailListSerializer(serializers.Serializer):
    results = WorkflowEmailSendSerializer(many=True, help_text="Sends, newest first.")
    has_more = serializers.BooleanField(help_text="Whether another page follows.")
    engagement_events_enabled = serializers.BooleanField(
        help_text="Whether the project records engagement events now. Sends made while it was off show no "
        "subject, delivery, opens or clicks."
    )


class WorkflowEmailDetailSerializer(WorkflowEmailSendSerializer):
    timeline = TransactionalEmailLogEventSerializer(
        many=True,
        help_text=f"The send, then deliveries, bounces, opens and clicks in the {ACTIVITY_WINDOW_DAYS} days after it, oldest first.",
    )


def _send_data(send: WorkflowEmailSend) -> dict[str, Any]:
    return {**asdict(send), "status": send.status.value}


class WorkflowEmailLogViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    schema = _PageSchema()
    scope_object = "hog_flow"
    scope_object_read_actions = ["list", "retrieve", "activity"]

    def dangerously_get_required_scopes(self, request: Any, view: Any) -> list[str] | None:
        # Sends name their recipients and distinct IDs, and activity reads the recipient's events.
        if self.action in ("list", "retrieve"):
            return ["hog_flow:read", "person:read"]
        if self.action == "activity":
            return ["hog_flow:read", "person:read", "query:read"]
        return None

    def initial(self, request: Any, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        user = request.user
        if not isinstance(user, User) or not posthoganalytics.feature_enabled(
            FEATURE_FLAG,
            user.distinct_id or str(user.uuid),
            groups={"organization": str(self.team.organization_id), "project": str(self.team.id)},
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            send_feature_flag_events=False,
        ):
            raise NotFound()

    def _workflow_access(self) -> WorkflowViewAccess:
        return get_workflow_view_access(team_id=self.team_id, user_access_control=self.user_access_control)

    def _require_access(self, *resources: APIScopeObject) -> None:
        # Session users skip API scopes, and access control checks only the hog_flow scope_object.
        for resource in resources:
            if not self.user_access_control.check_access_level_for_resource(resource, "viewer"):
                raise PermissionDenied(f"You need access to {resource} data to see workflow email recipients.")

    def _invocation_id(self, pk: str | None) -> UUID:
        try:
            return UUID(str(pk))
        except ValueError:
            raise NotFound()

    @validated_request(
        query_serializer=WorkflowEmailListQuerySerializer,
        responses={
            200: OpenApiResponse(response=WorkflowEmailListSerializer),
            403: OpenApiResponse(description="The user has no access to persons."),
            404: OpenApiResponse(description="The project has no such workflow, or the user may not view it."),
        },
        summary="List a workflow's email sends",
        operation_id="workflow_email_log_list",
        description=f"List the emails one workflow or broadcast sent, newest first. {ENGAGEMENT_NOTE}",
    )
    def list(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        self._require_access("person")
        query = request.validated_query_data
        with query_concurrency_slots(self.team):
            page = list_workflow_emails(
                self.team,
                cast(User, request.user),
                str(query["workflow_id"]),
                date_from=query.get("date_from"),
                date_to=query.get("date_to"),
                limit=query["limit"],
                offset=query["offset"],
                access=self._workflow_access(),
            )
        if page is None:
            raise NotFound()
        return Response(
            WorkflowEmailListSerializer(
                {
                    "results": [_send_data(send) for send in page.sends],
                    "has_more": page.has_more,
                    "engagement_events_enabled": page.engagement_events_enabled,
                }
            ).data
        )

    @validated_request(
        query_serializer=WorkflowEmailSendQuerySerializer,
        parameters=[INVOCATION_PARAMETER],
        responses={
            200: OpenApiResponse(response=WorkflowEmailDetailSerializer),
            403: OpenApiResponse(description="The user has no access to persons."),
            404: OpenApiResponse(description="The project has no such send, or the user may not view its workflow."),
        },
        summary="Get a workflow email send",
        description=f"Get one email a workflow sent, with its delivery timeline. {ENGAGEMENT_NOTE}",
    )
    def retrieve(self, request: ValidatedRequest, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        self._require_access("person")
        invocation_id = self._invocation_id(pk)
        with query_concurrency_slots(self.team):
            detail = get_workflow_email(
                self.team,
                cast(User, request.user),
                invocation_id,
                request.validated_query_data["action_id"],
                access=self._workflow_access(),
            )
        if detail is None:
            raise NotFound()
        data = {
            **_send_data(detail.send),
            "timeline": [
                {"kind": event.kind.value, "at": event.at, "reason": event.reason} for event in detail.timeline
            ],
        }
        return Response(WorkflowEmailDetailSerializer(data).data)

    @validated_request(
        query_serializer=WorkflowEmailSendQuerySerializer,
        parameters=[INVOCATION_PARAMETER],
        responses={
            200: OpenApiResponse(response=TransactionalEmailActivitySerializer),
            403: OpenApiResponse(description="The user has no access to persons or to querying events."),
            404: OpenApiResponse(description="The project has no such send, or the user may not view its workflow."),
        },
        summary="Get what a workflow email's recipient did around the send",
        description=f"The recipient's events in the {ACTIVITY_WINDOW_DAYS} days before and after one workflow email, "
        "with the sessions they belong to.",
    )
    @action(detail=True, methods=["GET"])
    def activity(self, request: ValidatedRequest, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        self._require_access("person", "query")
        invocation_id = self._invocation_id(pk)
        with query_concurrency_slots(self.team):
            activity = get_workflow_email_activity(
                self.team,
                cast(User, request.user),
                invocation_id,
                request.validated_query_data["action_id"],
                access=self._workflow_access(),
            )
        if activity is None:
            raise NotFound()
        return Response(TransactionalEmailActivitySerializer(asdict(activity)).data)
