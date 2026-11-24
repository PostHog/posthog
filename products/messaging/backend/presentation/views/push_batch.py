from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status

from posthog.api.fields import LengthFirstListField
from posthog.api.mixins import ResponseDeclaration
from posthog.enums import LabeledStrEnum

from products.messaging.backend.facade.transactional_email import (
    DeliveryUnavailable,
    EmailNotQueued,
    IdempotencyKeyInFlight,
    PushBatchRecipient,
    QueuedEmail,
    is_idempotency_key,
)
from products.messaging.backend.presentation.views.refusals import ExplainedRefusal

PUSH_BATCH_MAX_RECIPIENTS = 100
PUSH_BATCH_BODY_MAX_BYTES = 5 * 1024 * 1024
PUSH_RESULT_STATUS_BY_CODE = {
    "quota_limited": status.HTTP_429_TOO_MANY_REQUESTS,
    "idempotency_key_in_flight": status.HTTP_409_CONFLICT,
    "idempotency_key_reused": status.HTTP_422_UNPROCESSABLE_ENTITY,
}
UNCONFIRMED_PUSH = (
    "The push pipeline did not confirm this notification, so it may still go out. Send it again with the same "
    "`idempotency_key` within 24 hours of the first request that used it, so it goes out once."
)


class PushBatchRecipientSerializer(serializers.Serializer):
    distinct_id = serializers.CharField(
        max_length=400,
        help_text="Distinct ID of the person to notify. The notification goes to every device this person "
        "registered for the template's push channels. A person with no registered device gets nothing, and the "
        "send shows as skipped in the template's sends.",
    )
    message_data = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        default=dict,
        help_text="Values for this recipient's {{ variables.* }} placeholders, merged over the batch's "
        "`message_data`: a top-level key set here replaces the same key there.",
    )
    idempotency_key = serializers.CharField(
        trim_whitespace=False,
        help_text="A unique key for this recipient's notification, 1 to 255 visible ASCII characters, different for "
        "each recipient of the batch. Retrying with the same key and the same notification within 24 hours sends "
        "nothing new and returns the first send's `message_id`, also when the first send was a single send.",
    )

    def validate_idempotency_key(self, value: str) -> str:
        if not is_idempotency_key(value):
            raise serializers.ValidationError("Use 1 to 255 visible ASCII characters, with no spaces.")
        return value


class PushBatchRecipientsField(LengthFirstListField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            child=PushBatchRecipientSerializer(), allow_empty=False, max_length=PUSH_BATCH_MAX_RECIPIENTS, **kwargs
        )

    def run_child_validation(self, data: list[Any]) -> list[dict[str, Any]]:
        recipients = super().run_child_validation(data)
        positions: dict[str, int] = {}
        errors: dict[str, dict[str, Any]] = {}
        for index, recipient in enumerate(recipients):
            first = positions.setdefault(recipient["idempotency_key"], index)
            if first != index:
                errors[str(index)] = {
                    "idempotency_key": [
                        f"Recipient {first} has the same `idempotency_key`. Give each recipient its own key."
                    ]
                }
        if errors:
            raise serializers.ValidationError(errors)
        return recipients


class SendPushBatchSerializer(serializers.Serializer):
    template_id = serializers.UUIDField(
        help_text="ID of a push template made transactional, which holds the notification's title, body and push "
        "channels."
    )
    message_data = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        default=dict,
        help_text="Values for the template's {{ variables.* }} placeholders that every recipient shares, keyed by "
        "variable name.",
    )
    recipients = PushBatchRecipientsField(
        help_text=f"Who gets the notification: 1 to {PUSH_BATCH_MAX_RECIPIENTS} people, each sent their own "
        "notification with its own `message_id`."
    )


class PushBatchResultStatus(LabeledStrEnum):
    QUEUED = "queued", "Queued"


class PushBatchErrorSerializer(serializers.Serializer):
    code = serializers.CharField(
        help_text="Why this recipient's notification wasn't queued: `content_too_large`, `invalid_request`, "
        "`idempotency_key_reused`, `idempotency_key_in_flight`, `quota_limited`, `transactional_push_paused`, or "
        "`delivery_unavailable` when the push pipeline didn't confirm it, so it may still go out."
    )
    detail = serializers.CharField(help_text="What happened and what to do next, in words a person can read.")
    status = serializers.IntegerField(
        help_text="The HTTP status that goes with `code`: 429 for `quota_limited`, 409 for "
        "`idempotency_key_in_flight`, 422 for `idempotency_key_reused`, 503 for `delivery_unavailable`, and 400 for "
        "the others. The batch itself answers 200."
    )
    retryable = serializers.BooleanField(
        help_text="True when sending it again with the same `idempotency_key` can succeed: "
        "`delivery_unavailable` and `idempotency_key_in_flight`."
    )


class PushBatchResultSerializer(serializers.Serializer):
    message_id = serializers.CharField(
        help_text="ID of this recipient's notification, the same for every send with its `idempotency_key`, also "
        "when the result is an error."
    )
    status = serializers.ChoiceField(
        choices=PushBatchResultStatus.choices,
        required=False,
        help_text="`queued` when PostHog accepted the notification. It can still be skipped later, for example when "
        "the person has no registered device. Absent with `error`.",
    )
    replayed = serializers.BooleanField(
        required=False,
        help_text="True when an earlier request with the same `idempotency_key` already queued this notification, "
        "so no new one was sent. Absent with `error`.",
    )
    error = PushBatchErrorSerializer(
        required=False, help_text="Why this notification wasn't queued. Absent when it was."
    )


class SendPushBatchResponseSerializer(serializers.Serializer):
    results = PushBatchResultSerializer(many=True, help_text="One result per recipient, in the order of the request.")


PUSH_BATCH_RESPONSES: dict[int, ResponseDeclaration] = {
    200: OpenApiResponse(
        response=SendPushBatchResponseSerializer,
        description="The batch was read. Each result says whether that recipient's notification was queued, or why "
        "not.",
    ),
    400: OpenApiResponse(
        description="A field is invalid, the template isn't a transactional push template or its workflow is turned "
        "off, a recipient has no valid `idempotency_key` or shares one with another recipient, or there are more "
        f"than {PUSH_BATCH_MAX_RECIPIENTS} recipients"
    ),
    404: OpenApiResponse(description="Template not found"),
    413: OpenApiResponse(description="The request body is over 5 MiB"),
    429: OpenApiResponse(
        description="The batch would go over the send rate limit, or the project is over its quota, so nothing was sent"
    ),
    503: OpenApiResponse(
        description="The push pipeline did not confirm any notification of the batch. Some may still go out. Send "
        "the batch again with the same `idempotency_key` for each recipient"
    ),
}


def push_batch_too_large() -> ExplainedRefusal:
    return ExplainedRefusal(
        "The batch is larger than PostHog can send at once, so PostHog didn't send it.",
        code="content_too_large",
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        why=f"A batch send takes at most {PUSH_BATCH_BODY_MAX_BYTES // (1024 * 1024)} MiB of request body.",
        fix="Split the recipients into smaller batches.",
    )


def unconfirmed_push_batch() -> ExplainedRefusal:
    return ExplainedRefusal(
        "The push pipeline did not confirm the batch, so some of its notifications may still go out. To retry, send "
        "the batch again with the same `idempotency_key` for each recipient within 24 hours of the first request "
        "that used it, so each notification goes out once.",
        code="delivery_unavailable",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        why="PostHog's push pipeline didn't answer for any recipient of the batch.",
        fix="Send the batch again with the same `idempotency_key` for each recipient within 24 hours of its first "
        "request.",
    )


def push_batch_recipients(data: dict[str, Any]) -> list[PushBatchRecipient]:
    return [
        PushBatchRecipient(
            distinct_id=recipient["distinct_id"],
            idempotency_key=recipient["idempotency_key"],
            message_data={**data["message_data"], **recipient["message_data"]},
        )
        for recipient in data["recipients"]
    ]


def push_batch_response(results: tuple[QueuedEmail | EmailNotQueued, ...]) -> dict[str, Any]:
    return SendPushBatchResponseSerializer({"results": [_result(result) for result in results]}).data


def push_batch_outcome(result: QueuedEmail | EmailNotQueued) -> dict[str, Any]:
    if isinstance(result, QueuedEmail):
        return {"outcome": "replayed" if result.replayed else "queued"}
    if isinstance(result.error, DeliveryUnavailable):
        return {"outcome": "unavailable"}
    return {"outcome": "rejected", "error_code": result.error.code}


def _result(result: QueuedEmail | EmailNotQueued) -> dict[str, Any]:
    if isinstance(result, QueuedEmail):
        return {"message_id": result.message_id, "status": PushBatchResultStatus.QUEUED, "replayed": result.replayed}
    if isinstance(result.error, DeliveryUnavailable):
        error = {
            "code": "delivery_unavailable",
            "detail": UNCONFIRMED_PUSH,
            "status": status.HTTP_503_SERVICE_UNAVAILABLE,
            "retryable": True,
        }
    else:
        code = result.error.code
        error = {
            "code": code,
            "detail": str(result.error),
            "status": PUSH_RESULT_STATUS_BY_CODE.get(code, status.HTTP_400_BAD_REQUEST),
            "retryable": isinstance(result.error, IdempotencyKeyInFlight),
        }
    return {"message_id": result.message_id, "error": error}
