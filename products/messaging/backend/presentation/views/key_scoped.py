"""The transactional email viewsets at /api/messaging/, with the project taken from the project secret API key."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from django.core.exceptions import RequestDataTooBig
from django.utils.http import parse_header_parameters

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import UnsupportedMediaType
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from posthog.rate_limit import reserve_units

from products.messaging.backend.facade.transactional_email import (
    BatchTooLarge,
    DeliveryUnavailable,
    EmailBatchSent,
    QueuedEmail,
    TransactionalEmailError,
    check_email_batch,
    send_code_email_batch,
    send_email_batch,
    transactional_email_stage,
)
from products.messaging.backend.presentation.views.attachment_uploads import MessagingAttachmentsViewSet
from products.messaging.backend.presentation.views.email_batch import (
    BATCH_BODY_MAX_BYTES,
    EMAIL_BATCH_RESPONSES,
    SendEmailBatchSerializer,
    batch_too_large,
    email_batch_outcome,
    email_batch_response,
    unconfirmed_batch,
)
from products.messaging.backend.presentation.views.message_templates import (
    TRANSACTIONAL_EMAIL_SEND_SCOPE,
    MessagingSendViewSet,
    TransactionalEmailRejected,
    code_email,
    code_email_usage_properties,
    require_email_batch_sends,
    require_email_from_code,
    transactional_email_throttles,
)
from products.messaging.backend.presentation.views.refusals import ExplainedRefusal
from products.messaging.backend.presentation.views.topic_preferences import TopicPreferencesViewSet
from products.messaging.backend.presentation.views.transactional_email_status import MessagingEmailsViewSet


class KeyScopedMessagingSendViewSet(MessagingSendViewSet):
    team_from_project_secret_api_key = True
    psak_allowed_actions = ["email", "email_batch"]
    transactional_email_send_actions = ("email", "email_batch")

    def initial(self, request: Any, *args: Any, **kwargs: Any) -> None:
        if self.action == "email_batch":
            self._batch_properties = {"batch_id": str(uuid4()), "has_idempotency_key": None}
            if int(request.META.get("CONTENT_LENGTH") or 0) > BATCH_BODY_MAX_BYTES:
                raise RequestDataTooBig()
        super().initial(request, *args, **kwargs)

    def check_throttles(self, request: Any) -> None:
        if self.action == "email_batch":
            self._check_batch_before_throttles(request)
        super().check_throttles(request)

    def _check_batch_before_throttles(self, request: Any) -> None:
        with transactional_email_stage("feature_flag"):
            require_email_batch_sends(self.team)
            if parse_header_parameters(request.content_type)[0] != JSONParser.media_type:
                raise UnsupportedMediaType(request.content_type)
            if isinstance(request.data, Mapping) and "template_key" in request.data:
                require_email_from_code(self.team)
            else:
                self._require_transactional_email_flag()

    def body_too_large(self) -> ExplainedRefusal:
        return batch_too_large() if self.action == "email_batch" else super().body_too_large()

    @extend_schema(
        request={"application/json": SendEmailBatchSerializer},
        responses=EMAIL_BATCH_RESPONSES,
        summary="Send a transactional email to a batch of recipients",
        description=(
            "Send one transactional email to up to 100 recipients in one request. Each recipient gets its own email, "
            "with its own `message_id` and `idempotency_key`, the same email a single send to that recipient makes. "
            "Name a template made transactional in `template_id`, where each recipient's `message_data` is merged "
            "over the shared `message_data`. Or send content your code rendered with a `template_key`, the same for "
            "every recipient. The response holds one result per recipient, in the order of the request: a recipient "
            "can fail while the others are queued. Each result carries the recipient's `message_id`, so you can read "
            "its status. A refusal of the whole batch, such as an exhausted quota or a paused email, answers with "
            "an error and no `results`, even on a retry whose first request queued some recipients. Read each "
            "recipient's status by its `idempotency_key` then. Each recipient counts against the send rate limit. "
            "Needs the `transactional_email:write` scope."
        ),
    )
    @action(
        detail=False,
        methods=["POST"],
        parser_classes=[JSONParser],
        required_scopes=[TRANSACTIONAL_EMAIL_SEND_SCOPE],
    )
    def email_batch(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        serializer = SendEmailBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.validated_data = data = serializer.validated_data
        self._end_request_validation()
        self._batch_properties = {
            **self._batch_properties,
            "batch_size": len(data["recipients"]),
            "has_idempotency_key": True,
        }
        email = code_email(data) if "template_key" in data else None
        try:
            recipients = check_email_batch(data["recipients"], message_data=data["message_data"], email=email)
            reserve_units(transactional_email_throttles(self.team_id), request, self, len(recipients) - 1)
            if email is not None:
                self._require_code_email_access(email.key)
                sent = send_code_email_batch(self.team, email, recipients)
                usage_properties = code_email_usage_properties(email)
            else:
                with transactional_email_stage("template_lookup"):
                    template = self.get_object()
                sent = send_email_batch(self.team, template, recipients, message_data=data["message_data"])
                usage_properties = {"template_id": str(template.id)}
        except TransactionalEmailError as e:
            raise TransactionalEmailRejected(e) from None
        except BatchTooLarge:
            self._report_transactional_email_send(request, {"outcome": "rejected", "error_code": "content_too_large"})
            raise batch_too_large() from None
        except DeliveryUnavailable:
            self._report_transactional_email_send(request, {"outcome": "unavailable"})
            raise unconfirmed_batch() from None
        self._report_batch(request, sent, usage_properties)
        return Response(email_batch_response(sent), status=status.HTTP_200_OK)

    def _report_batch(self, request: Any, sent: EmailBatchSent, usage_properties: dict[str, Any]) -> None:
        with transactional_email_stage("usage_event"):
            for result in sent.results:
                self._report_transactional_email_send(request, {**usage_properties, **email_batch_outcome(result)})
        if any(isinstance(result, QueuedEmail) and not result.replayed for result in sent.results):
            self._report_first_code_send_after_commit(request, usage_properties.get("addressed_by", "template_id"))


class KeyScopedMessagingAttachmentsViewSet(MessagingAttachmentsViewSet):
    team_from_project_secret_api_key = True


class KeyScopedMessagingEmailsViewSet(MessagingEmailsViewSet):
    team_from_project_secret_api_key = True


class KeyScopedTopicPreferencesViewSet(TopicPreferencesViewSet):
    team_from_project_secret_api_key = True
