from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status

from posthog.api.fields import LengthFirstListField
from posthog.api.mixins import ResponseDeclaration
from posthog.enums import LabeledStrEnum

from products.messaging.backend.facade.transactional_email import (
    BatchRecipient,
    DeliveryUnavailable,
    EmailBatchSent,
    EmailNotQueued,
    InvalidRecipient,
    QueuedEmail,
    is_idempotency_key,
)
from products.messaging.backend.presentation.views.code_send_fields import (
    CODE_SEND_EXTRA_FIELDS,
    validate_pipeline_address,
)
from products.messaging.backend.presentation.views.message_templates import (
    DISTINCT_ID_HELP_TEXT,
    SendEmailSerializer,
    SendWarningSerializer,
    TransactionalEmailRejected,
)
from products.messaging.backend.presentation.views.refusals import ExplainedRefusal

BATCH_MAX_RECIPIENTS = 100
BATCH_BODY_MAX_BYTES = 5 * 1024 * 1024
BATCH_REFUSED_FIELDS = ("scheduled_at", *CODE_SEND_EXTRA_FIELDS)
FIELDS_THAT_FAIL_ONE_RECIPIENT = frozenset({"to", "distinct_id"})
UNCONFIRMED_EMAIL = (
    "The email pipeline did not confirm this email, so it may still go out. Send it again with the same "
    "`idempotency_key` within 24 hours of the first request that used it, so it goes out once."
)


class EmailBatchRecipientSerializer(serializers.Serializer):
    to = serializers.EmailField(
        validators=[validate_pipeline_address],
        help_text="Email address of this recipient. An address PostHog can't send to fails only this recipient's "
        "result, with `invalid_recipient`.",
    )
    distinct_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, max_length=400, help_text=DISTINCT_ID_HELP_TEXT
    )
    message_data = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        default=dict,
        help_text="Data for this recipient, merged over the batch's `message_data`: a top-level key set here "
        "replaces the same key there. Only a batch with `template_id` takes it.",
    )
    idempotency_key = serializers.CharField(
        trim_whitespace=False,
        help_text="A unique key for this recipient's email, 1 to 255 visible ASCII characters, different for each "
        "recipient of the batch. Retrying with the same key and the same email within 24 hours sends nothing new and "
        "returns the first send's `message_id`, also when the first send was a single send.",
    )

    def validate_idempotency_key(self, value: str) -> str:
        if not is_idempotency_key(value):
            raise serializers.ValidationError("Use 1 to 255 visible ASCII characters, with no spaces.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if (unknown := next((name for name in self.initial_data if name not in self.fields), None)) is not None:
            raise serializers.ValidationError(
                {unknown: "A recipient takes only `to`, `distinct_id`, `message_data` and `idempotency_key`."}
            )
        return attrs


class EmailBatchRecipientsField(LengthFirstListField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            child=EmailBatchRecipientSerializer(), allow_empty=False, max_length=BATCH_MAX_RECIPIENTS, **kwargs
        )

    def run_child_validation(self, data: list[Any]) -> list[BatchRecipient]:
        recipients: list[BatchRecipient] = []
        errors: dict[str, dict[str, Any]] = {}
        positions: dict[str, int] = {}
        for index, item in enumerate(data):
            serializer = EmailBatchRecipientSerializer(data=item)
            if serializer.is_valid():
                fields = serializer.validated_data
                recipient = BatchRecipient(
                    to=fields["to"],
                    idempotency_key=fields["idempotency_key"],
                    distinct_id=fields.get("distinct_id") or None,
                    message_data=fields["message_data"],
                )
            elif set(serializer.errors) <= FIELDS_THAT_FAIL_ONE_RECIPIENT:
                field, messages = next(iter(serializer.errors.items()))
                recipient = BatchRecipient(
                    to=str(item.get("to", "")),
                    idempotency_key=str(item["idempotency_key"]),
                    refusal=InvalidRecipient(f"`{field}`: {messages[0]}"),
                )
            else:
                errors[str(index)] = {
                    name: value
                    for name, value in serializer.errors.items()
                    if name not in FIELDS_THAT_FAIL_ONE_RECIPIENT
                }
                continue
            first = positions.setdefault(recipient.idempotency_key, index)
            if first != index:
                errors[str(index)] = {
                    "idempotency_key": [
                        f"Recipient {first} has the same `idempotency_key`. Give each recipient its own key."
                    ]
                }
            recipients.append(recipient)
        if errors:
            raise serializers.ValidationError(errors)
        return recipients


class SendEmailBatchSerializer(SendEmailSerializer):
    recipients = EmailBatchRecipientsField(
        help_text=f"Who gets the email: 1 to {BATCH_MAX_RECIPIENTS} recipients, each sent its own email with its "
        "own `message_id`."
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        for name in ("to", "distinct_id", *BATCH_REFUSED_FIELDS):
            fields.pop(name, None)
        return fields

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if (unknown := next((field for field in self.initial_data if field not in self.fields), None)) is not None:
            raise serializers.ValidationError(
                {
                    unknown: "A batch send doesn't take this field, so PostHog didn't send it. Each recipient's `to` "
                    "and `distinct_id` go in `recipients`."
                }
            )
        data = super().validate(data)
        if "template_key" in data and any("message_data" in item for item in self.initial_data["recipients"]):
            raise serializers.ValidationError(
                {
                    "recipients": "A batch with `template_key` sends the same content to every recipient, so a "
                    "recipient can't carry `message_data`."
                }
            )
        return data


class EmailBatchResultStatus(LabeledStrEnum):
    QUEUED = "queued", "Queued"


class EmailBatchErrorSerializer(serializers.Serializer):
    code = serializers.CharField(
        help_text="Why this recipient's email wasn't queued: `invalid_recipient`, `invalid_request`, "
        "`content_too_large`, `idempotency_key_reused`, `sandbox_recipient_not_member`, or `delivery_unavailable` "
        "when the email pipeline didn't confirm it, so it may still go out."
    )
    detail = serializers.CharField(help_text="What happened and what to do next, in words a person can read.")
    status = serializers.IntegerField(
        help_text="The HTTP status that goes with `code`: 422 for `idempotency_key_reused` and "
        "`sandbox_recipient_not_member`, 503 for `delivery_unavailable`, and 400 for the others. The batch itself "
        "answers 200."
    )
    retryable = serializers.BooleanField(
        help_text="True when sending it again with the same `idempotency_key` can succeed. Only "
        "`delivery_unavailable` is retryable."
    )


class EmailBatchResultSerializer(serializers.Serializer):
    message_id = serializers.CharField(
        help_text="ID of this recipient's email, the same for every send with its `idempotency_key`. Read the "
        "email's status with it, also when the result is an error."
    )
    status = serializers.ChoiceField(
        choices=EmailBatchResultStatus.choices,
        required=False,
        help_text="`queued` when PostHog accepted the email. The email can still be skipped later, for example "
        "when the address is on the suppression list, so read its status to see whether it went out. Absent with "
        "`error`.",
    )
    replayed = serializers.BooleanField(
        required=False,
        help_text="True when an earlier request with the same `idempotency_key` already queued this email, so no "
        "new email was sent. False doesn't prove this request sent it: an earlier request may still be on its way. "
        "Absent with `error`.",
    )
    error = EmailBatchErrorSerializer(required=False, help_text="Why this email wasn't queued. Absent when it was.")


class SendEmailBatchResponseSerializer(serializers.Serializer):
    results = EmailBatchResultSerializer(many=True, help_text="One result per recipient, in the order of the request.")
    warnings = SendWarningSerializer(
        many=True,
        required=False,
        help_text="Things the caller should act on although emails were queued. Left out when there are none.",
    )

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)
        if not data.get("warnings"):
            data.pop("warnings", None)
        return data


EMAIL_BATCH_RESPONSES: dict[int, ResponseDeclaration] = {
    200: OpenApiResponse(
        response=SendEmailBatchResponseSerializer,
        description="The batch was read. Each result says whether that recipient's email was queued.",
    ),
    400: OpenApiResponse(
        description="The shared email is invalid or can't be sent, its workflow isn't active, a recipient has no valid `idempotency_key` or "
        "shares one with another recipient, a field a batch doesn't take is present, there are more than "
        f"{BATCH_MAX_RECIPIENTS} recipients, or the shared content or `message_data` is over 256 KiB"
    ),
    403: OpenApiResponse(description="The sandbox sender isn't available for this organization, so nothing was sent"),
    404: OpenApiResponse(description="Template not found, or batch sends aren't available for this project"),
    409: OpenApiResponse(
        description="Batch sends aren't available for this project yet, so nothing was sent. Send each email on its "
        "own instead"
    ),
    413: OpenApiResponse(
        description="The request body is over 5 MiB, or the batch is larger than the email pipeline takes at once"
    ),
    415: OpenApiResponse(description="The request body isn't JSON"),
    422: OpenApiResponse(description="Email sending is suspended for this project, or paused for this email"),
    429: OpenApiResponse(
        description="The batch would go over the send rate limit, or the project is over its email quota, so "
        "nothing was sent"
    ),
    503: OpenApiResponse(
        description="The email pipeline did not confirm the batch. Some of its emails may go out. Read each "
        "recipient's status by its `idempotency_key`"
    ),
}


def batch_too_large() -> ExplainedRefusal:
    return ExplainedRefusal(
        "The batch is larger than PostHog can send at once, so PostHog didn't send it.",
        code="content_too_large",
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        why=f"A batch send takes at most {BATCH_BODY_MAX_BYTES // (1024 * 1024)} MiB of request body, and the email "
        "pipeline takes a limited amount of data in one batch.",
        fix="Split the recipients into smaller batches.",
    )


def unconfirmed_batch() -> ExplainedRefusal:
    return ExplainedRefusal(
        "The email pipeline did not confirm the batch, so some of its emails may still go out. To retry, send the "
        "batch again with the same `idempotency_key` for each recipient within 24 hours of the first request that "
        "used it, so each email goes out once.",
        code="delivery_unavailable",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        why="PostHog's email pipeline didn't answer for each recipient of the batch.",
        fix="Send the batch again with the same `idempotency_key` for each recipient within 24 hours of its first "
        "request.",
    )


def email_batch_response(sent: EmailBatchSent) -> dict[str, Any]:
    return SendEmailBatchResponseSerializer(
        {"results": [_result(result) for result in sent.results], "warnings": list(sent.warnings)}
    ).data


def email_batch_outcome(result: QueuedEmail | EmailNotQueued) -> dict[str, Any]:
    if isinstance(result, QueuedEmail):
        return {"outcome": "replayed" if result.replayed else "queued"}
    if isinstance(result.error, DeliveryUnavailable):
        return {"outcome": "unavailable"}
    return {"outcome": "rejected", "error_code": result.error.code}


def _result(result: QueuedEmail | EmailNotQueued) -> dict[str, Any]:
    if isinstance(result, QueuedEmail):
        return {"message_id": result.message_id, "status": EmailBatchResultStatus.QUEUED, "replayed": result.replayed}
    if isinstance(result.error, DeliveryUnavailable):
        error = {
            "code": "delivery_unavailable",
            "detail": UNCONFIRMED_EMAIL,
            "status": status.HTTP_503_SERVICE_UNAVAILABLE,
            "retryable": True,
        }
    else:
        code = result.error.code
        status_code = TransactionalEmailRejected.STATUS_BY_CODE.get(code, status.HTTP_400_BAD_REQUEST)
        error = {"code": code, "detail": str(result.error), "status": status_code, "retryable": False}
    return {"message_id": result.message_id, "error": error}
