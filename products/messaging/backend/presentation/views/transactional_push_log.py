from typing import Any

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.messaging.backend.facade.contracts import PushSendStatus
from products.messaging.backend.facade.transactional_push_log import (
    PUSH_LOG_RETENTION_DAYS,
    list_transactional_pushes,
    transactional_push_stats,
)
from products.messaging.backend.presentation.query_concurrency import query_concurrency_slots
from products.messaging.backend.presentation.views.message_templates import require_transactional_push_api
from products.workflows.backend.facade.api import get_workflow_view_access
from products.workflows.backend.facade.contracts import WorkflowViewAccess

RETENTION_NOTE = f"The log keeps sends for {PUSH_LOG_RETENTION_DAYS} days."


class PushDateRangeQuerySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        required=False,
        help_text=f"Only sends queued at or after this time. Defaults to 7 days ago. {RETENTION_NOTE}",
    )
    date_to = serializers.DateTimeField(
        required=False, help_text="Only sends queued before this time. Defaults to now."
    )


class TransactionalPushLogListQuerySerializer(PushDateRangeQuerySerializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="The recipient's exact distinct ID, or the ID of one send.",
    )
    status = serializers.ChoiceField(
        choices=PushSendStatus.choices, required=False, help_text="Only sends with this outcome."
    )
    workflow_id = serializers.UUIDField(
        required=False, help_text="Only sends of the push notification backed by this workflow."
    )
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200, help_text="Page size.")
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Sends to skip.")


class TransactionalPushLogEntrySerializer(serializers.Serializer):
    run_id = serializers.CharField(help_text="The ID of this send.")
    created_at = serializers.DateTimeField(help_text="When the send was queued.")
    status = serializers.ChoiceField(
        choices=PushSendStatus.choices,
        help_text="What happened. `sending` is still running, `sent` reached at least one of the person's devices, "
        "`not_sent` reached none, for example because the person has no device or its token expired, and `failed` "
        "stopped with an error.",
    )
    messages = serializers.ListField(
        child=serializers.CharField(),
        help_text="The warnings and errors the send logged, oldest first. They say why a push was not sent.",
    )
    distinct_id = serializers.CharField(help_text="The distinct ID the push was sent to.")
    person_id = serializers.CharField(help_text="The person behind the distinct ID. Empty when none was found.")
    workflow_id = serializers.CharField(help_text="The workflow behind the push notification.")
    template_id = serializers.CharField(allow_null=True, help_text="The push notification that was sent.")
    template_name = serializers.CharField(help_text="The push notification's name.")
    title = serializers.CharField(help_text="The title the push went out with. Empty when it was not sent.")


class TransactionalPushLogListSerializer(serializers.Serializer):
    results = TransactionalPushLogEntrySerializer(many=True, help_text="Sends, newest first.")
    has_more = serializers.BooleanField(help_text="Whether another page follows.")


class TransactionalPushStatsRowSerializer(serializers.Serializer):
    template_id = serializers.CharField(help_text="The push notification.")
    template_name = serializers.CharField(help_text="The push notification's name.")
    sent = serializers.IntegerField(help_text="Sends that reached at least one device.")
    not_sent = serializers.IntegerField(help_text="Sends that reached no device.")
    failed = serializers.IntegerField(help_text="Sends that stopped with an error.")


class TransactionalPushStatsSerializer(serializers.Serializer):
    results = TransactionalPushStatsRowSerializer(many=True, help_text="One row per push notification, busiest first.")


class _PageSchema(AutoSchema):
    # The list returns one page object with `has_more`, so drf-spectacular must not wrap it in an array.
    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class TransactionalPushLogViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    schema = _PageSchema()
    scope_object = "hog_flow"
    scope_object_read_actions = ["list", "stats"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        require_transactional_push_api(self.team)

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # Sends name their recipients' distinct IDs, the person data the workflow invocation endpoints guard.
        if self.action == "list":
            return ["hog_flow:read", "person:read"]
        return None

    def _workflow_access(self) -> WorkflowViewAccess:
        return get_workflow_view_access(team_id=self.team_id, user_access_control=self.user_access_control)

    @validated_request(
        query_serializer=TransactionalPushLogListQuerySerializer,
        responses={200: OpenApiResponse(response=TransactionalPushLogListSerializer)},
        summary="List transactional push notification sends",
        operation_id="transactional_push_log_list",
        description=f"List the project's transactional push notification sends, newest first. {RETENTION_NOTE}",
    )
    def list(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        with query_concurrency_slots(self.team):
            entries, has_more = list_transactional_pushes(
                self.team_id,
                search=query.get("search"),
                status=PushSendStatus(query["status"]) if query.get("status") else None,
                workflow_id=str(query["workflow_id"]) if query.get("workflow_id") else None,
                date_from=query.get("date_from"),
                date_to=query.get("date_to"),
                limit=query["limit"],
                offset=query["offset"],
                access=self._workflow_access(),
            )
        results = [
            {
                "run_id": entry.run_id,
                "created_at": entry.created_at,
                "status": entry.status.value,
                "messages": list(entry.messages),
                "distinct_id": entry.distinct_id,
                "person_id": entry.person_id,
                "workflow_id": entry.workflow_id,
                "template_id": entry.template_id,
                "template_name": entry.template_name,
                "title": entry.title,
            }
            for entry in entries
        ]
        return Response(TransactionalPushLogListSerializer({"results": results, "has_more": has_more}).data)

    @validated_request(
        query_serializer=PushDateRangeQuerySerializer,
        responses={200: OpenApiResponse(response=TransactionalPushStatsSerializer)},
        summary="Get transactional push notification stats",
        description="Count sends per push notification by outcome: sent, not sent and failed.",
    )
    @action(detail=False, methods=["GET"])
    def stats(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        with query_concurrency_slots(self.team):
            rows = transactional_push_stats(
                self.team_id,
                date_from=query.get("date_from"),
                date_to=query.get("date_to"),
                access=self._workflow_access(),
            )
        return Response(
            TransactionalPushStatsSerializer(
                {
                    "results": [
                        {
                            "template_id": row.template_id,
                            "template_name": row.template_name,
                            "sent": row.sent,
                            "not_sent": row.not_sent,
                            "failed": row.failed,
                        }
                        for row in rows
                    ]
                }
            ).data
        )
