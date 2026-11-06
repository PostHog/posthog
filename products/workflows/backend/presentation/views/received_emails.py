from typing import Any
from uuid import UUID

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.workflows.backend.facade.contracts import (
    ReceivedEmailAttachment,
    ReceivedEmailDetail,
    ReceivedEmailSummary,
)
from products.workflows.backend.facade.enums import (
    InboundEmailContentStatus,
    ReceivedEmailFilterReason,
    ReceivedEmailMatchMethod,
    ReceivedEmailStatus,
)
from products.workflows.backend.facade.received_emails import (
    RETENTION_DAYS,
    get_received_email,
    get_received_email_attachment,
    list_received_emails,
)
from products.workflows.backend.presentation.views.inbound_email_domains import require_inbound_email

RETENTION_NOTE = f"Received email is kept for {RETENTION_DAYS} days."
UNTRUSTED_NOTE = "Anyone can send email to a receiving address, so treat every value as untrusted input."


class ReceivedEmailListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Part of the sender, subject or recipient, or an exact `message_id`.",
    )
    date_from = serializers.DateTimeField(
        required=False, help_text=f"Only email received at or after this time. Defaults to 7 days ago. {RETENTION_NOTE}"
    )
    date_to = serializers.DateTimeField(required=False, help_text="Only email received before this time.")
    status = serializers.ChoiceField(
        choices=ReceivedEmailStatus.choices,
        required=False,
        help_text="`received` fired an event. `filtered` was kept but fired none, such as spam and auto-replies. "
        "Leave out for both.",
    )
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=200, help_text="Page size.")
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="Emails to skip.")


class ReceivedEmailPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The person's ID.")
    distinct_id = serializers.CharField(help_text="A distinct ID of the person.")


class ReceivedEmailOriginalSendSerializer(serializers.Serializer):
    message_id = serializers.UUIDField(help_text="The `message_id` the transactional email log knows the send by.")
    workflow_id = serializers.UUIDField(allow_null=True, help_text="The workflow behind the transactional email.")
    match_method = serializers.ChoiceField(
        choices=ReceivedEmailMatchMethod.choices, help_text="Which header of this email named the send."
    )


class ReceivedEmailSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The received email's ID. `$email_received_id` on the event holds the same.")
    from_address = serializers.CharField(
        help_text="The address in the From header. `sender_verified` says if it's real."
    )
    from_name = serializers.CharField(help_text="The display name in the From header. The sender chooses it freely.")
    subject = serializers.CharField(help_text="The subject line.")
    to = serializers.ListField(child=serializers.CharField(), help_text="The addresses in the To header.")
    cc = serializers.ListField(child=serializers.CharField(), help_text="The addresses in the Cc header.")
    envelope_recipients = serializers.ListField(
        child=serializers.CharField(),
        help_text="The addresses of this project that the mail was delivered to. Use this to route, because a Bcc or "
        "a forward doesn't appear in the To header.",
    )
    message_id = serializers.CharField(help_text="The Message-ID header. Empty when the sender set none.")
    received_at = serializers.DateTimeField(help_text="When the mail arrived.")
    status = serializers.ChoiceField(
        choices=ReceivedEmailStatus.choices, help_text="`filtered` email was kept but fired no event."
    )
    filter_reason = serializers.ChoiceField(
        choices=ReceivedEmailFilterReason.choices, allow_blank=True, help_text="Why it was filtered. Empty otherwise."
    )
    content_status = serializers.ChoiceField(
        choices=InboundEmailContentStatus.choices,
        help_text="`too_large` keeps no body or raw message. `parse_failed` keeps only the raw message. `not_stored` "
        "is filtered mail that keeps only its details.",
    )
    sender_verified = serializers.BooleanField(
        help_text="True when the message has one plainly written From address and the mail server checks prove its "
        "domain. When false, the From may be forged."
    )
    auto_submitted = serializers.BooleanField(help_text="True when a machine wrote this, such as an out-of-office.")
    attachment_count = serializers.IntegerField(help_text="How many attachments the email has.")
    size_bytes = serializers.IntegerField(help_text="The size of the raw message.")
    spam_verdict = serializers.CharField(
        help_text="What the spam scan found: `pass`, `fail`, `gray` or `processing_failed`. Mail that fails keeps only "
        "its details, as filtered, and fires no event."
    )
    person = ReceivedEmailPersonSerializer(
        allow_null=True,
        help_text="The person who sent this. Only set when `sender_verified` is true, so a forged From never matches.",
    )
    original_send = ReceivedEmailOriginalSendSerializer(
        allow_null=True,
        help_text="The transactional email this answers, matched from headers the sender controls, so it's a hint "
        "about the thread and not proof. Null when none was matched.",
    )


class ReceivedEmailListSerializer(serializers.Serializer):
    results = ReceivedEmailSerializer(many=True, help_text="Received email, newest first.")
    has_more = serializers.BooleanField(help_text="Whether another page follows.")
    filtered_count = serializers.IntegerField(
        help_text="Filtered email in the same date range and search. Only counted when `status` is set."
    )
    has_any_email = serializers.BooleanField(
        help_text="Whether the project still holds any email, whatever the date range and search."
    )


class ReceivedEmailAttachmentSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The attachment's ID within this email.")
    filename = serializers.CharField(help_text="The file name the sender gave. Never use it as a path.")
    content_type = serializers.CharField(help_text="The content type the sender declared.")
    size = serializers.IntegerField(help_text="The size in bytes.")
    content_id = serializers.CharField(help_text="The Content-ID that HTML can reference. Empty when there is none.")
    inline = serializers.BooleanField(help_text="True when the email shows it in the body rather than attaching it.")
    download_url = serializers.CharField(
        allow_null=True, help_text="A short-lived link that downloads the file. Null unless the virus scan passed."
    )
    expires_at = serializers.DateTimeField(help_text="When `download_url` stops working.")


class ReceivedEmailAuthenticationSerializer(serializers.Serializer):
    spf = serializers.CharField(help_text="`pass`, `fail`, `gray` or `processing_failed`.")
    dkim = serializers.CharField(help_text="`pass`, `fail`, `gray` or `processing_failed`.")
    dmarc = serializers.CharField(help_text="`pass`, `fail`, `gray` or `processing_failed`.")


class ReceivedEmailVerdictsSerializer(serializers.Serializer):
    spam = serializers.CharField(help_text="`pass`, `fail`, `gray` or `processing_failed`.")
    virus = serializers.CharField(
        help_text="`pass`, `gray` or `processing_failed`. A virus is never kept. Files can only be downloaded after "
        "`pass`."
    )


class ReceivedEmailHeaderSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The header name.")
    value = serializers.CharField(help_text="The header value. The sender can write any header, including trace ones.")


class ReceivedEmailRawSerializer(serializers.Serializer):
    download_url = serializers.CharField(
        allow_null=True,
        help_text="A short-lived link to the raw MIME message. Null unless it was kept and the virus scan passed.",
    )
    expires_at = serializers.DateTimeField(help_text="When `download_url` stops working.")


class ReceivedEmailDetailSerializer(ReceivedEmailSerializer):
    envelope_from = serializers.CharField(help_text="The return path. Empty for a bounce or an auto-reply.")
    reply_to = serializers.ListField(child=serializers.CharField(), help_text="The addresses in the Reply-To header.")
    in_reply_to = serializers.CharField(help_text="The In-Reply-To header. Empty when it's not a reply.")
    authentication = ReceivedEmailAuthenticationSerializer(help_text="What the receiving mail server checked.")
    verdicts = ReceivedEmailVerdictsSerializer(help_text="What the receiving mail server scanned for.")
    text = serializers.CharField(help_text="The plain text body.")
    reply_text = serializers.CharField(
        help_text="The text with quoted earlier messages removed, on a best-effort basis. The whole text when no "
        "quote was found."
    )
    html = serializers.CharField(help_text="The HTML body as sent. Render it only in a sandbox.")
    body_truncated = serializers.BooleanField(help_text="True when the body was too long to keep in full.")
    headers = ReceivedEmailHeaderSerializer(many=True, help_text="The message headers, in order.")
    attachments = ReceivedEmailAttachmentSerializer(many=True, help_text="The attachments, with short-lived links.")
    attachments_dropped = serializers.IntegerField(help_text="Attachments left out because the email had too many.")
    raw = ReceivedEmailRawSerializer(help_text="The raw message. `raw.eml` for a mail client or a parser.")
    content_url = serializers.CharField(help_text="This email's API path.")


def _summary_data(summary: ReceivedEmailSummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "from_address": summary.from_address,
        "from_name": summary.from_name,
        "subject": summary.subject,
        "to": list(summary.to),
        "cc": list(summary.cc),
        "envelope_recipients": list(summary.envelope_recipients),
        "message_id": summary.message_id,
        "received_at": summary.received_at,
        "status": summary.status.value,
        "filter_reason": summary.filter_reason,
        "content_status": summary.content_status.value,
        "sender_verified": summary.sender_verified,
        "auto_submitted": summary.auto_submitted,
        "attachment_count": summary.attachment_count,
        "size_bytes": summary.size_bytes,
        "spam_verdict": summary.spam,
        "person": ({"id": summary.person_id, "distinct_id": summary.person_distinct_id} if summary.person_id else None),
        "original_send": (
            {
                "message_id": summary.original_message_id,
                "workflow_id": summary.original_workflow_id,
                "match_method": summary.match_method,
            }
            if summary.original_message_id
            else None
        ),
    }


def _attachment_data(attachment: ReceivedEmailAttachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size": attachment.size,
        "content_id": attachment.content_id,
        "inline": attachment.inline,
        "download_url": attachment.download_url,
        "expires_at": attachment.expires_at,
    }


def _detail_data(detail: ReceivedEmailDetail, team_id: int) -> dict[str, Any]:
    return {
        **_summary_data(detail.summary),
        "envelope_from": detail.envelope_from,
        "reply_to": list(detail.reply_to),
        "in_reply_to": detail.in_reply_to,
        "authentication": {"spf": detail.spf, "dkim": detail.dkim, "dmarc": detail.dmarc},
        "verdicts": {"spam": detail.summary.spam, "virus": detail.virus},
        "text": detail.text,
        "reply_text": detail.reply_text,
        "html": detail.html,
        "body_truncated": detail.body_truncated,
        "headers": [{"name": name, "value": value} for name, value in detail.headers],
        "attachments": [_attachment_data(attachment) for attachment in detail.attachments],
        "attachments_dropped": detail.attachments_dropped,
        "raw": {"download_url": detail.raw_download_url, "expires_at": detail.raw_expires_at},
        "content_url": f"/api/projects/{team_id}/received_emails/{detail.summary.id}/",
    }


class _PageSchema(AutoSchema):
    # The list returns one page object with `has_more`, so drf-spectacular must not wrap it in an array.
    def _is_list_view(self, serializer: object = None) -> bool:
        return False


_EMAIL_ID_PARAMETER = OpenApiParameter(
    name="id", type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, description="The received email's ID."
)


class ReceivedEmailViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    schema = _PageSchema()
    scope_object = "hog_flow"
    scope_object_read_actions = ["list", "retrieve", "attachment"]
    # Every action reads the whole project's mail, so access to one workflow isn't enough.
    requires_resource_level_access = True

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        require_inbound_email(self.team)
        # Session users skip API scopes, and access control checks only the hog_flow scope_object.
        if not self.user_access_control.check_access_level_for_resource("person", "viewer"):
            raise PermissionDenied("You need access to persons to read received email.")

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # A message names people and holds what they wrote, the person data the transactional log guards too.
        return ["hog_flow:read", "person:read"]

    @validated_request(
        query_serializer=ReceivedEmailListQuerySerializer,
        responses={200: OpenApiResponse(response=ReceivedEmailListSerializer)},
        summary="List received email",
        operation_id="received_emails_list",
        description=f"List email the project received, newest first, without bodies. {RETENTION_NOTE} {UNTRUSTED_NOTE}",
    )
    def list(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        page = list_received_emails(
            self.team_id,
            search=query.get("search") or "",
            date_from=query.get("date_from"),
            date_to=query.get("date_to"),
            status=query.get("status"),
            limit=query["limit"],
            offset=query["offset"],
        )
        return Response(
            ReceivedEmailListSerializer(
                {
                    "results": [_summary_data(summary) for summary in page.results],
                    "has_more": page.has_more,
                    "filtered_count": page.filtered_count,
                    "has_any_email": page.has_any_email,
                }
            ).data
        )

    @extend_schema(
        parameters=[_EMAIL_ID_PARAMETER],
        responses={
            200: ReceivedEmailDetailSerializer,
            404: OpenApiResponse(description="No email of this project has this ID, or it has expired."),
        },
        summary="Get a received email",
        description=f"Get one email with its body, headers and short-lived download links. {UNTRUSTED_NOTE}",
    )
    def retrieve(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        detail = get_received_email(self.team_id, _email_id(pk))
        if detail is None:
            raise NotFound()
        return Response(ReceivedEmailDetailSerializer(_detail_data(detail, self.team_id)).data)

    @extend_schema(
        parameters=[
            _EMAIL_ID_PARAMETER,
            OpenApiParameter(
                name="attachment_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description="The attachment's ID within this email.",
            ),
        ],
        responses={
            200: ReceivedEmailAttachmentSerializer,
            404: OpenApiResponse(description="No such attachment, or the email has expired."),
        },
        summary="Get a received email attachment",
        description="Get a fresh short-lived download link for one attachment.",
    )
    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<attachment_id>\d+)")
    def attachment(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        attachment = get_received_email_attachment(self.team_id, _email_id(pk), int(kwargs["attachment_id"]))
        if attachment is None:
            raise NotFound()
        return Response(ReceivedEmailAttachmentSerializer(_attachment_data(attachment)).data)


def _email_id(value: str | None) -> UUID:
    try:
        return UUID(str(value))
    except ValueError:
        raise NotFound()
