from dataclasses import asdict
from typing import Any
from uuid import UUID

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.messaging.backend.facade.contracts import (
    EmailDeliveryStatus,
    EmailLogEventKind,
    EmailStatsGroupBy,
    TransactionalEmailLogEntry,
)
from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_RETENTION_DAYS
from products.messaging.backend.presentation.views.message_templates import require_transactional_email_api
from products.messaging.backend.services.transactional_email_log import (
    MAX_CONVERSION_WINDOW_DAYS,
    get_transactional_email,
    list_transactional_emails,
    transactional_email_results,
    transactional_email_stats,
)

RETENTION_NOTE = f"The log keeps sends for {EMAIL_STATUS_RETENTION_DAYS} days."


class DateRangeQuerySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        required=False,
        help_text=f"Only sends queued at or after this time. Defaults to 7 days ago. {RETENTION_NOTE}",
    )
    date_to = serializers.DateTimeField(
        required=False, help_text="Only sends queued before this time. Defaults to now."
    )


class TransactionalEmailLogListQuerySerializer(DateRangeQuerySerializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="A `message_id` for an exact match, or part of the recipient's email address.",
    )
    status = serializers.ChoiceField(
        choices=EmailDeliveryStatus.choices, required=False, help_text="Only sends in this delivery status."
    )
    workflow_id = serializers.UUIDField(
        required=False, help_text="Only sends of the transactional email backed by this workflow."
    )
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200, help_text="Page size.")
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Sends to skip.")


class TransactionalEmailLogEntrySerializer(serializers.Serializer):
    message_id = serializers.CharField(help_text="The `message_id` that the send returned.")
    created_at = serializers.DateTimeField(help_text="When the send was queued.")
    status = serializers.ChoiceField(
        choices=EmailDeliveryStatus.choices,
        help_text="The email's delivery status. `queued` waits to go out, `sent` reached the email provider, "
        "`delivered` was accepted by the recipient's mail server, `bounced` and `complained` came back later, and "
        "`failed` was not sent.",
    )
    status_at = serializers.DateTimeField(help_text="When the email reached its delivery status.")
    reason = serializers.CharField(
        allow_null=True, help_text="Why a failed email was not sent, or the bounce type. Null otherwise."
    )
    recipient = serializers.CharField(help_text="The address the email was sent to.")
    workflow_id = serializers.CharField(help_text="The workflow behind the transactional email.")
    template_id = serializers.CharField(
        allow_null=True, help_text="The transactional email template. Null when it no longer exists."
    )
    template_name = serializers.CharField(help_text="The template's name. Empty when it was deleted.")
    sending_domain = serializers.CharField(help_text="The domain the email was sent from. Empty before it was sent.")
    opened = serializers.BooleanField(help_text="Whether the recipient opened the email.")
    clicked = serializers.BooleanField(help_text="Whether the recipient clicked a link in the email.")


class TransactionalEmailLogListSerializer(serializers.Serializer):
    results = TransactionalEmailLogEntrySerializer(many=True, help_text="Sends, newest first.")
    has_more = serializers.BooleanField(help_text="Whether another page follows.")


class TransactionalEmailLogEventSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=EmailLogEventKind.choices,
        help_text="What happened. The delivery statuses, plus `opened` and `clicked` for what the recipient did.",
    )
    at = serializers.DateTimeField(help_text="When it happened.")
    reason = serializers.CharField(allow_null=True, help_text="Why a send failed, or the bounce type. Null otherwise.")


class TransactionalEmailLogDetailSerializer(TransactionalEmailLogEntrySerializer):
    timeline = TransactionalEmailLogEventSerializer(many=True, help_text="Everything that happened, oldest first.")
    subject = serializers.CharField(help_text="The subject the email went out with. Empty when it was never sent.")
    distinct_id = serializers.CharField(help_text="The distinct ID the send named. Empty when it named none.")
    action_id = serializers.CharField(
        help_text="The workflow step that sent the email, which the rendered email is stored under. Empty when no "
        "rendered email was stored."
    )
    sensitive = serializers.BooleanField(
        help_text="True when the template is marked sensitive, so no rendered body or subject values are kept."
    )


class TransactionalEmailStatsQuerySerializer(DateRangeQuerySerializer):
    group_by = serializers.ChoiceField(
        choices=EmailStatsGroupBy.choices,
        default=EmailStatsGroupBy.TEMPLATE,
        help_text="Count per template or per sending domain.",
    )


class TransactionalEmailStatsRowSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="The template ID or the sending domain.")
    label = serializers.CharField(help_text="The template name or the sending domain. Empty for a deleted template.")
    sent = serializers.IntegerField(help_text="Emails that reached the email provider.")
    delivered = serializers.IntegerField(help_text="Emails the recipient's mail server accepted.")
    bounced = serializers.IntegerField(help_text="Emails that bounced.")
    complained = serializers.IntegerField(help_text="Emails the recipient marked as spam.")
    opened = serializers.IntegerField(help_text="Emails the recipient opened.")
    clicked = serializers.IntegerField(help_text="Emails where the recipient clicked a link.")
    failed = serializers.IntegerField(help_text="Emails that were not sent.")


class TransactionalEmailStatsSerializer(serializers.Serializer):
    results = TransactionalEmailStatsRowSerializer(many=True, help_text="One row per group, busiest first.")


class TransactionalEmailResultsQuerySerializer(DateRangeQuerySerializer):
    workflow_id = serializers.UUIDField(help_text="The workflow behind the transactional email.")
    event = serializers.CharField(help_text="The event that counts as a conversion, such as `signed_up`.")
    window_days = serializers.IntegerField(
        required=False,
        default=7,
        min_value=1,
        max_value=MAX_CONVERSION_WINDOW_DAYS,
        help_text="How many days after the first send the event still counts.",
    )
    revenue_property = serializers.CharField(
        required=False, allow_blank=True, help_text="An event property holding a revenue amount to add up."
    )


class TransactionalEmailResultsSerializer(serializers.Serializer):
    recipients = serializers.IntegerField(help_text="People the email was sent to in the date range.")
    converted = serializers.IntegerField(help_text="Of those, people who did the event within the window.")
    revenue = serializers.FloatField(help_text="The sum of the revenue property on those events.")
    median_hours_to_convert = serializers.FloatField(
        allow_null=True, help_text="Median hours from the first send to the first conversion. Null when none converted."
    )


def _entry_data(entry: TransactionalEmailLogEntry) -> dict[str, Any]:
    return {
        "message_id": entry.message_id,
        "created_at": entry.created_at,
        "status": entry.status.value,
        "status_at": entry.status_at,
        "reason": entry.reason,
        "recipient": entry.recipient,
        "workflow_id": entry.workflow_id,
        "template_id": entry.template_id,
        "template_name": entry.template_name,
        "sending_domain": entry.sending_domain,
        "opened": entry.opened,
        "clicked": entry.clicked,
    }


class _PageSchema(AutoSchema):
    # The list returns one page object with `has_more`, so drf-spectacular must not wrap it in an array.
    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class TransactionalEmailLogViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    schema = _PageSchema()
    scope_object = "hog_flow"
    scope_object_read_actions = ["list", "retrieve", "stats", "results"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        require_transactional_email_api(self.team)

    @validated_request(
        query_serializer=TransactionalEmailLogListQuerySerializer,
        responses={200: OpenApiResponse(response=TransactionalEmailLogListSerializer)},
        summary="List transactional email sends",
        operation_id="transactional_email_log_list",
        description=f"List the project's transactional email sends, newest first. {RETENTION_NOTE}",
    )
    def list(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        entries, has_more = list_transactional_emails(
            self.team_id,
            search=query.get("search"),
            status=EmailDeliveryStatus(query["status"]) if query.get("status") else None,
            workflow_id=str(query["workflow_id"]) if query.get("workflow_id") else None,
            date_from=query.get("date_from"),
            date_to=query.get("date_to"),
            limit=query["limit"],
            offset=query["offset"],
        )
        return Response(
            TransactionalEmailLogListSerializer(
                {"results": [_entry_data(entry) for entry in entries], "has_more": has_more}
            ).data
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="The `message_id` that the send returned.",
            )
        ],
        responses={
            200: TransactionalEmailLogDetailSerializer,
            404: OpenApiResponse(description="No send of this project has this ID, or it is older than the log keeps."),
        },
        summary="Get a transactional email send",
        description="Get one send with its timeline: when it was queued, sent, delivered, opened and clicked.",
    )
    def retrieve(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            message_id = UUID(str(pk))
        except ValueError:
            raise NotFound()
        detail = get_transactional_email(self.team_id, message_id)
        if detail is None:
            raise NotFound()
        data = {
            **_entry_data(detail.entry),
            "timeline": [
                {"kind": event.kind.value, "at": event.at, "reason": event.reason} for event in detail.timeline
            ],
            "subject": detail.subject,
            "distinct_id": detail.distinct_id,
            "action_id": detail.action_id,
            "sensitive": detail.sensitive,
        }
        return Response(TransactionalEmailLogDetailSerializer(data).data)

    @validated_request(
        query_serializer=TransactionalEmailStatsQuerySerializer,
        responses={200: OpenApiResponse(response=TransactionalEmailStatsSerializer)},
        summary="Get transactional email delivery stats",
        description="Count sends by delivery status, opens and clicks, per template or per sending domain.",
    )
    @action(detail=False, methods=["GET"])
    def stats(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        rows = transactional_email_stats(
            self.team_id,
            EmailStatsGroupBy(query["group_by"]),
            date_from=query.get("date_from"),
            date_to=query.get("date_to"),
        )
        return Response(TransactionalEmailStatsSerializer({"results": [asdict(row) for row in rows]}).data)

    @validated_request(
        query_serializer=TransactionalEmailResultsQuerySerializer,
        responses={200: OpenApiResponse(response=TransactionalEmailResultsSerializer)},
        summary="Get what happened after a transactional email",
        description="Of the people a transactional email was sent to, count those who did an event within a window "
        "after their first send, and add up the revenue on those events.",
    )
    @action(detail=False, methods=["GET"])
    def results(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        outcome = transactional_email_results(
            self.team,
            str(query["workflow_id"]),
            query["event"],
            window_days=query["window_days"],
            revenue_property=query.get("revenue_property") or None,
            date_from=query.get("date_from"),
            date_to=query.get("date_to"),
        )
        return Response(TransactionalEmailResultsSerializer(asdict(outcome)).data)
