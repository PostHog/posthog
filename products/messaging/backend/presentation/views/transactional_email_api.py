"""What every route of the transactional email API shares: the flag, the error envelope, throttles and the send."""

import re
from typing import Any

import structlog
import posthoganalytics
from rest_framework import exceptions, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.settings import api_settings

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.permissions import is_authenticated_via_project_secret_api_key
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.messaging.backend.facade.contracts import TEMPLATE_KEY_MAX_LENGTH, TEMPLATE_KEY_PATTERN, QueuedEmail
from products.messaging.backend.facade.templates import MessageTemplateRow
from products.messaging.backend.facade.transactional_email import (
    DeliveryUnavailable,
    TransactionalEmailError,
    send_transactional_email,
)
from products.workflows.backend.facade.api import WorkflowAccessDenied, WorkflowNotFound
from products.workflows.backend.facade.workflows import get_workflow

logger = structlog.get_logger(__name__)


TRANSACTIONAL_EMAIL_API_FLAG = "workflows-transactional-email-api"


class TransactionalEmailIdentifiersSerializer(serializers.Serializer):
    distinct_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=400,
        help_text="Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, "
        "clicked, bounced) and the send itself are recorded against that person. Defaults to the recipient's email "
        "address. The template can't read the person's properties, so pass everything it needs in `message_data`.",
    )


class SendTransactionalEmailSerializer(serializers.Serializer):
    to = serializers.EmailField(help_text="Email address of the recipient.")
    identifiers = TransactionalEmailIdentifiersSerializer(
        required=False, help_text="Who the email is for, used to attribute engagement events."
    )
    message_data = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        default=dict,
        help_text="Data for the template's Liquid placeholders, available as `variables`. "
        'For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`.',
    )


class SendTransactionalEmailResponseSerializer(serializers.Serializer):
    message_id = serializers.CharField(
        help_text="ID of the queued send. Delivery and engagement are reported against the template asynchronously."
    )


class TemplateErrorSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Error class, such as `invalid_request`.")
    code = serializers.CharField(help_text="Stable error code to branch on, such as `invalid_template_key`.")
    detail = serializers.CharField(help_text="What went wrong.")
    attr = serializers.CharField(allow_null=True, help_text="The request field the error is about, if any.")
    why = serializers.CharField(required=False, help_text="Why PostHog refuses the request.")
    fix = serializers.CharField(required=False, help_text="What to change before you retry.")
    docs_url = serializers.URLField(required=False, help_text="Documentation for this error code.")


TRANSACTIONAL_EMAIL_DOCS_URL = "https://posthog.com/docs/workflows/transactional-email-api"


@frozen
class TemplateRefusal:
    """A refusal of the template routes, with what to change before the caller retries."""

    code: str
    detail: str
    attr: str | None
    why: str
    fix: str
    type: str = "invalid_request"

    @property
    def docs_url(self) -> str:
        return f"{TRANSACTIONAL_EMAIL_DOCS_URL}#{self.code}"


@frozen
class FieldError:
    attr: str
    message: str


def invalid_template_key(key: object, attr: str = "key") -> TemplateRefusal | None:
    if isinstance(key, str) and len(key) <= TEMPLATE_KEY_MAX_LENGTH and re.fullmatch(TEMPLATE_KEY_PATTERN, key):
        return None
    return TemplateRefusal(
        code="invalid_template_key",
        detail=f"The key can have at most {TEMPLATE_KEY_MAX_LENGTH} letters, digits, hyphens (-) and underscores (_).",
        attr=attr,
        why="Code names the template by its key in every project, so the key must stay the same.",
        fix="Use a key like `password-reset`.",
    )


def invalid_request(errors: Any, *, why: str, retry: str) -> TemplateRefusal:
    error = first_field_error(errors)
    return TemplateRefusal(
        code="invalid_request",
        detail=f"{error.attr}: {error.message}",
        attr=error.attr,
        why=why,
        fix=f"Fix `{error.attr}` and {retry}.",
    )


def first_field_error(errors: Any, path: tuple[str, ...] = ()) -> FieldError:
    if isinstance(errors, dict):
        field, nested = next(iter(errors.items()))
        # An error about a nested object as a whole names the object.
        field_path = path if field == api_settings.NON_FIELD_ERRORS_KEY else (*path, str(field))
        return first_field_error(nested, field_path)
    if isinstance(errors, list) and errors and not isinstance(errors[0], str):
        return first_field_error(errors[0], path)
    return FieldError(attr="__".join(path), message=str(errors[0] if isinstance(errors, list) else errors))


class TransactionalEmailRejected(exceptions.APIException):
    STATUS_BY_CODE = {"quota_limited": 429}
    # The caller has to change the request. Without this the error handler reports a server error.
    default_type = "invalid_request"

    def __init__(self, error: TransactionalEmailError) -> None:
        self.status_code = self.STATUS_BY_CODE.get(error.code, status.HTTP_400_BAD_REQUEST)
        super().__init__(detail=str(error), code=error.code)


class TransactionalEmailUnavailable(exceptions.APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The email pipeline is unavailable. Try again shortly."
    default_code = "delivery_unavailable"


class TransactionalEmailBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_burst"
    rate = "600/minute"


class TransactionalEmailSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "transactional_email_sustained"
    rate = "20000/hour"


class TransactionalEmailTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate across all of a project's secret API keys."""

    scope = "transactional_email_psak_team_burst"
    rate = "600/minute"


class TransactionalEmailTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "transactional_email_psak_team_sustained"
    rate = "20000/hour"


TRANSACTIONAL_EMAIL_THROTTLES = [
    TransactionalEmailBurstThrottle,
    TransactionalEmailSustainedThrottle,
    TransactionalEmailTeamBurstThrottle,
    TransactionalEmailTeamSustainedThrottle,
]


class TransactionalEmailViewSetMixin(TeamAndOrgViewSetMixin):
    """What every route of the transactional email API shares: the flag, workflow access and the send."""

    def _require_transactional_email_flag(self) -> None:
        if not posthoganalytics.feature_enabled(
            TRANSACTIONAL_EMAIL_API_FLAG,
            str(self.team.uuid),
            groups={"organization": str(self.team.organization_id)},
            group_properties={"organization": {"id": str(self.team.organization_id)}},
            send_feature_flag_events=False,
        ):
            raise NotFound()

    def _require_workflow_editor(self, hog_flow_id: Any) -> None:
        # A project secret API key has no user to check, and its scope already limits it to sending and uploads.
        if is_authenticated_via_project_secret_api_key(self.request):
            return
        try:
            get_workflow(
                team_id=self.team_id,
                workflow_id=str(hog_flow_id),
                user_access_control=self.user_access_control,
                required_level="editor",
            )
        except WorkflowAccessDenied:
            raise exceptions.PermissionDenied(
                "You need editor access to this template's transactional email workflow."
            ) from None
        except WorkflowNotFound:
            return

    @staticmethod
    def _auth_method(request: Request) -> str:
        return "project_secret_api_key" if is_authenticated_via_project_secret_api_key(request) else "user"

    def _send_transactional_email(
        self, request: Any, template: MessageTemplateRow, data: dict[str, Any], *, usage: dict[str, str]
    ) -> QueuedEmail:
        if template.transactional_hog_flow_id:
            self._require_workflow_editor(template.transactional_hog_flow_id)
        outcome: dict[str, Any] = {"outcome": "error"}
        try:
            queued = send_transactional_email(
                self.team,
                template.id,
                to=data["to"],
                distinct_id=(data.get("identifiers") or {}).get("distinct_id") or None,
                message_data=data["message_data"],
            )
            outcome = {"outcome": "queued"}
        except TransactionalEmailError as e:
            outcome = {"outcome": "rejected", "error_code": e.code}
            raise TransactionalEmailRejected(e)
        except DeliveryUnavailable:
            outcome = {"outcome": "unavailable"}
            raise TransactionalEmailUnavailable() from None
        finally:
            self._report_transactional_email_send(request, {"template_id": str(template.id), **usage, **outcome})
        return queued

    def _report_transactional_email_send(self, request: Any, properties: dict[str, Any]) -> None:
        self._report_api_usage(request, "transactional email api send", properties)

    def _report_api_usage(self, request: Any, event: str, properties: dict[str, Any]) -> None:
        # report_user_action drops the synthetic user behind a project secret API key, so capture directly.
        try:
            posthoganalytics.capture(
                distinct_id=request.user.distinct_id,
                event=event,
                properties={"team_id": self.team_id, "auth_method": self._auth_method(request), **properties},
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional email API usage event", event_name=event, error=str(e))
