import re
from collections.abc import Mapping, Sequence
from dataclasses import fields as dataclass_fields
from types import SimpleNamespace
from typing import Any

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import exceptions, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.dataclasses import frozen
from posthog.event_usage import groups, report_user_action
from posthog.models import User
from posthog.permissions import is_authenticated_via_project_secret_api_key
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.cdp.backend.presentation.hog_functions import build_html_wrap_design
from products.messaging.backend.facade.api import (
    UnlayerNotConfiguredError,
    UnlayerRenderError,
    apply_design_operations,
    render_design_html,
    validate_design,
)
from products.messaging.backend.facade.contracts import (
    TEMPLATE_KEY_MAX_LENGTH,
    TEMPLATE_KEY_PATTERN,
    ContentHashState,
    QueuedEmail,
    TemplateKeyRefused,
    TemplateManagedBy,
    TemplateManagedByCode,
    TemplateSource,
    TemplateUpload,
    TemplateUploadResult,
    TemplateWriteIntent,
)
from products.messaging.backend.facade.templates import (
    MessageCategoryNotInTeam,
    MessageTemplateMissing,
    MessageTemplateRow,
    UploadedTemplate,
    adopt_template,
    check_template_key_write,
    check_template_write,
    create_template,
    get_template,
    is_adoption,
    is_release,
    list_templates,
    release_template,
    save_template_content,
    save_template_fields,
    team_category_id,
    upload_template,
)
from products.messaging.backend.facade.transactional_email import (
    DeliveryUnavailable,
    TransactionalEmailError,
    make_transactional,
    send_transactional_email,
)
from products.messaging.backend.presentation.views.serializers import DesignOperationSerializer
from products.notifications.backend.facade.api import publish_resource_edited
from products.workflows.backend.facade.api import WorkflowAccessDenied, WorkflowNotFound
from products.workflows.backend.facade.workflows import get_workflow

logger = structlog.get_logger(__name__)


# Shallow skeleton of the Unlayer design document — enough structure for API callers
# (and the LLMs behind MCP tools) to author against; the full row/column/content
# shape is documented in the designing-email-templates skill.
@extend_schema_field(
    {
        "type": "object",
        "properties": {
            "counters": {
                "type": "object",
                "description": 'Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}.',
            },
            "schemaVersion": {"type": "integer", "description": "Design schema version, e.g. 16."},
            "body": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Any unique string."},
                    "rows": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}.",
                    },
                    "headers": {"type": "array", "items": {"type": "object"}},
                    "footers": {"type": "array", "items": {"type": "object"}},
                    "values": {
                        "type": "object",
                        "description": "Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor.",
                    },
                },
                "required": ["rows"],
            },
        },
        "required": ["body", "schemaVersion"],
    }
)
class UnlayerDesignField(serializers.JSONField):
    pass


class EmailTemplateSerializer(serializers.Serializer):
    subject = serializers.CharField(
        required=False,
        help_text="Email subject line. Supports Liquid templating. Required for email-type templates.",
    )
    preheader = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Inbox preview text shown after the subject. Supports Liquid templating.",
    )
    text = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Plain-text fallback body for clients that can't render the email.",
    )
    html = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Rendered email body — derived from the design at save time. "
        "The visual editor's save path supplies it directly; omit it otherwise.",
    )
    design = UnlayerDesignField(
        required=False,
        help_text="Design JSON for PostHog's visual email editor — the authoring surface and source of "
        "truth. The server renders the sent email from it, and it opens as editable blocks in the editor. "
        "Full schema in the designing-email-templates skill.",
    )


class MessageTemplateContentSerializer(serializers.Serializer):
    templating = serializers.ChoiceField(
        choices=["liquid"],
        default="liquid",
        help_text="Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.",
    )
    email = EmailTemplateSerializer(
        required=False,
        allow_null=True,
        help_text="Email message content. Replaced as a whole on update — send the complete object.",
    )


@extend_schema_field(OpenApiTypes.UUID)
class MessageTemplateCategoryField(serializers.Field):
    """A category id that must belong to the template's team. Errors match a primary key related field."""

    default_error_messages = serializers.PrimaryKeyRelatedField.default_error_messages

    def run_validation(self, data: Any = serializers.empty) -> Any:
        # A DRF related field reads an empty string as null, and clients send "" to clear the category.
        if data == "":
            data = None
        return super().run_validation(data)

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, bool):
            self.fail("incorrect_type", data_type=type(data).__name__)
        try:
            return team_category_id(self.context["team_id"], data)
        except MessageCategoryNotInTeam:
            self.fail("does_not_exist", pk_value=data)
        except (TypeError, ValueError):
            self.fail("incorrect_type", data_type=type(data).__name__)

    def to_representation(self, value: Any) -> Any:
        return value


class MessageTemplateSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(max_length=400, help_text="Human-readable template name shown in the library.")
    description = serializers.CharField(
        allow_blank=True,
        required=False,
        style={"base_template": "textarea.html"},
        help_text="What the template is for and when to use it.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    content = MessageTemplateContentSerializer(
        required=False,
        help_text="Template content keyed by channel. Replaced as a whole on update, not merged.",
    )
    created_by = UserBasicSerializer(read_only=True)
    type = serializers.CharField(
        max_length=24,
        allow_blank=True,
        required=False,
        help_text="Message channel of the template. Currently 'email'.",
    )
    message_category = MessageTemplateCategoryField(
        required=False,
        allow_null=True,
        help_text="Message category ID to file the template under. Must belong to the same project.",
    )
    deleted = serializers.BooleanField(
        required=False, help_text="Soft-delete flag. Set true to remove the template from the library."
    )
    transactional_hog_flow_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="The workflow that sends this template over the transactional email API. Null until the "
        "template is made transactional. Each content save writes a new version of it.",
    )
    key = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Stable identifier code uses to upload and send this template, unique within the project. Null "
        "for templates that have no key. Set once, by the first upload or by a PATCH whose only field is `key`.",
    )
    managed_by = serializers.ChoiceField(
        choices=TemplateManagedBy.choices,
        read_only=True,
        allow_null=True,
        help_text="Who owns the content. `code` when it was uploaded from a repository: PostHog then refuses edits, and "
        "the template changes through its next upload. To edit it in PostHog, send a PATCH whose only field is "
        "`managed_by` set to `gui`. `gui` or null when it is edited in PostHog.",
    )
    source_repository = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Repository the template was last uploaded from, such as `github.com/example/app`.",
    )
    source_path = serializers.CharField(
        read_only=True, allow_null=True, help_text="Path of the template file in the source repository."
    )
    source_ref = serializers.CharField(
        read_only=True, allow_null=True, help_text="Commit or branch the template was last uploaded from."
    )
    content_hash = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Hash of the published subject, preheader, HTML and text, as `v1:` and 64 hex characters. Changes "
        "with every save that changes them.",
    )

    def validate(self, data: Any) -> Any:
        template_type = data.get("type")
        email = data.get("content", {}).get("email") if data.get("content") else None
        if template_type == "email" and email and not email.get("subject"):
            raise serializers.ValidationError(
                {"content": {"email": {"subject": "Subject is required for email templates."}}}
            )
        # Programmatically authored templates often supply html without a design, which the
        # visual editor can't open. Wrap the html in a single custom HTML block; the stored
        # html stays untouched, so nothing about the sent email changes.
        if email and email.get("html") and not email.get("design"):
            email["design"] = build_html_wrap_design(email["html"])
        # Design-only saves get their html rendered server-side (the send path uses html
        # verbatim). A submitted html is trusted as-is — that's the visual editor's own export.
        if email and email.get("design") and not email.get("html"):
            try:
                email["html"] = render_design_html(email["design"])
            except UnlayerNotConfiguredError:
                raise serializers.ValidationError(
                    {
                        "content": {
                            "email": {
                                "design": "Design rendering is not configured on this instance — an administrator "
                                "must set UNLAYER_API_KEY to enable saving design-authored templates."
                            }
                        }
                    }
                )
            except UnlayerRenderError as e:
                raise serializers.ValidationError(
                    {"content": {"email": {"design": f"Rendering the design to HTML failed: {e}"}}}
                )
        return data


class MessageTemplateUpdateSerializer(MessageTemplateSerializer):
    key = serializers.CharField(
        required=False,
        max_length=TEMPLATE_KEY_MAX_LENGTH,
        help_text="Give a template that has no key one, so code can take it over: the next upload under this key "
        "updates this template and keeps its id, workflow and sender. Send it as the only field of the PATCH. Letters, "
        "digits, hyphens (-) and underscores (_). Set once: a template that has a key keeps it.",
    )


class DesignPatchSerializer(serializers.Serializer):
    operations = serializers.ListField(
        child=DesignOperationSerializer(),
        allow_empty=False,
        help_text=(
            "Ordered edits applied atomically to a template's Unlayer design: the stored design is read, the ops "
            "are applied in order, the result is validated and re-rendered to HTML, and it's saved only if valid — "
            "otherwise the template is unchanged. Reference blocks by id so you never resend the whole design."
        ),
    )


TEMPLATE_ID_PARAMETER = OpenApiParameter(
    name="id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="A UUID string identifying this message template.",
)


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


class MakeTransactionalSerializer(serializers.Serializer):
    from_integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of the verified email sender integration the email is sent from. Defaults to the project's "
        "default sender.",
    )


class SendTransactionalEmailResponseSerializer(serializers.Serializer):
    message_id = serializers.CharField(
        help_text="ID of the queued send. Delivery and engagement are reported against the template asynchronously."
    )


class TemplateSourceSerializer(serializers.Serializer):
    repository = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        help_text="Host and path of the repository the file is in, such as `github.com/example/app`.",
    )
    path = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        help_text="Path of the template file in the repository, such as `emails/welcome.html`.",
    )
    ref = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        help_text="Commit or branch the file was uploaded from.",
    )


class UploadTemplateSerializer(serializers.Serializer):
    # Content is stored byte for byte as sent, so the content hash a client computes matches the stored one.
    name = serializers.CharField(max_length=400, help_text="Template name shown in the template library.")
    subject = serializers.CharField(
        trim_whitespace=False, help_text="Email subject line. Supports Liquid, such as `{{ variables.first_name }}`."
    )
    html = serializers.CharField(
        trim_whitespace=False,
        help_text="Email body as HTML, stored as sent. Supports Liquid, such as `{{ variables.first_name }}`.",
    )
    text = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Plain-text body for email clients that can't show HTML. Leaving it out removes the stored one.",
    )
    preheader = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Inbox preview text shown after the subject. Leaving it out removes the stored one.",
    )
    source = TemplateSourceSerializer(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        required=False,
        help_text="Where the template file lives, so people in PostHog can find it. Leaving it out, or a part of "
        "it, keeps what is stored.",
    )
    if_not_superseded = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Set it on uploads a program makes on its own, such as after a send answered `template_outdated`. "
        "When newer content already replaced this content, the upload changes nothing and answers `superseded`. "
        "Leave it out to publish the content in any case, such as to roll back to earlier content.",
    )


class UploadTemplateResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the template.")
    key = serializers.CharField(help_text="Key of the template.")
    result = serializers.ChoiceField(
        choices=TemplateUploadResult.choices,
        help_text="`created`: the upload made a new template. `updated`: it published the uploaded content. "
        "`unchanged`: the template already had this content, so nothing was published. `superseded`: the upload "
        "set `if_not_superseded` and newer content already replaced this content, so nothing was published.",
    )
    content_hash = serializers.CharField(
        help_text="Hash of the published content, as `v1:` and 64 hex characters. Send it with an email to check "
        "PostHog holds the content you hold. After `superseded` it is the hash of the newer content."
    )
    managed_by = serializers.ChoiceField(
        choices=TemplateManagedBy.choices,
        help_text="`code` after every upload except `superseded`, which changes nothing.",
    )
    source = TemplateSourceSerializer(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        help_text="Where the template file lives, as stored after the upload."
    )
    transactional_hog_flow_id = serializers.UUIDField(
        help_text="The workflow that sends this template. Each upload that changes the content writes a new version "
        "of it."
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
    if isinstance(key, str) and len(key) <= TEMPLATE_KEY_MAX_LENGTH and re.match(TEMPLATE_KEY_PATTERN, key):
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


TEMPLATE_KEY_PARAMETER = OpenApiParameter(
    name="key",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.PATH,
    description="Key of the template, chosen by you. Letters, digits, hyphens (-) and underscores (_), at most 400 "
    "characters. The same key names the template in every project.",
)


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
        # report_user_action drops the synthetic user behind a project secret API key, so capture directly.
        try:
            posthoganalytics.capture(
                distinct_id=request.user.distinct_id,
                event="transactional email api send",
                properties={"team_id": self.team_id, "auth_method": self._auth_method(request), **properties},
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional email usage event", error=str(e))


MANAGED_BY_CODE_RESPONSE = OpenApiResponse(
    response=TemplateErrorSerializer,
    description="The template is managed by code. `immutable`: change its file and upload it, or release it first",
)
TEMPLATE_UPDATE_SCHEMA = extend_schema(
    parameters=[TEMPLATE_ID_PARAMETER], responses={200: MessageTemplateSerializer, 403: MANAGED_BY_CODE_RESPONSE}
)
TEMPLATE_PARTIAL_UPDATE_SCHEMA = extend_schema(
    parameters=[TEMPLATE_ID_PARAMETER],
    request=MessageTemplateUpdateSerializer,
    responses={
        200: MessageTemplateSerializer,
        400: OpenApiResponse(
            response=TemplateErrorSerializer,
            description="A field is invalid. For `key`: `invalid_template_key`, `key_already_set`, `key_in_use`, or "
            "`invalid_request` when it is sent with other fields",
        ),
        403: MANAGED_BY_CODE_RESPONSE,
    },
)


@extend_schema_view(
    retrieve=extend_schema(parameters=[TEMPLATE_ID_PARAMETER]),
    update=TEMPLATE_UPDATE_SCHEMA,
    partial_update=TEMPLATE_PARTIAL_UPDATE_SCHEMA,
    destroy=extend_schema(parameters=[TEMPLATE_ID_PARAMETER]),
)
class MessageTemplatesViewSet(
    TransactionalEmailViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]
    # `design` and `send` are custom write actions; list them so programmatic callers (MCP/personal API key)
    # get hog_flow:write checked instead of being rejected as an action with no declared scope.
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "design",
        "send",
        "make_transactional",
        "upload",
    ]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    # A project secret API key can only send and upload. Template CRUD stays session/personal API key/OAuth only.
    psak_allowed_actions = ["send", "upload"]

    serializer_class = MessageTemplateSerializer

    def get_throttles(self):
        if self.action in ("send", "upload"):
            return [throttle() for throttle in TRANSACTIONAL_EMAIL_THROTTLES]
        return super().get_throttles()

    def dangerously_get_object(self) -> MessageTemplateRow:
        # Team scoping happens in the facade lookup, because the view has no queryset to filter.
        # DRF's detail OPTIONS metadata also calls get_object(), so the lookup must live here.
        try:
            template = get_template(self.team_id, self.kwargs["pk"])
        except MessageTemplateMissing:
            raise NotFound()
        self.check_object_permissions(self.request, template)
        return template

    def check_object_permissions(self, request: Request, obj: Any) -> None:
        super().check_object_permissions(request, obj)
        if request.method not in permissions.SAFE_METHODS:
            check_template_write(obj, self._write_intent())

    def _write_intent(self) -> TemplateWriteIntent:
        payload = self.request.data
        return TemplateWriteIntent(action=self.action, payload=payload if isinstance(payload, Mapping) else {})

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, TemplateManagedByCode):
            refusal = TemplateRefusal(code=exc.code, detail=exc.detail, attr=None, why=exc.why, fix=exc.fix)
            return Response(TemplateErrorSerializer(refusal).data, status=status.HTTP_403_FORBIDDEN)
        if isinstance(exc, TemplateKeyRefused):
            refusal = TemplateRefusal(code=exc.code, detail=exc.detail, attr="key", why=exc.why, fix=exc.fix)
            return Response(TemplateErrorSerializer(refusal).data, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)

    def _with_creators(self, templates: Sequence[MessageTemplateRow]) -> list[SimpleNamespace]:
        creator_ids = {template.created_by_id for template in templates if template.created_by_id}
        creators = {user.id: user for user in User.objects.filter(id__in=creator_ids)} if creator_ids else {}
        return [
            SimpleNamespace(
                **{field.name: getattr(template, field.name) for field in dataclass_fields(template)},
                created_by=creators.get(template.created_by_id) if template.created_by_id else None,
                message_category=template.message_category_id,
            )
            for template in templates
        ]

    def _serialize(self, template: MessageTemplateRow) -> Any:
        return self.get_serializer(self._with_creators([template])[0]).data

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        templates = list_templates(self.team_id)
        page = self.paginate_queryset(templates)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(self._with_creators(page), many=True).data)
        return Response(self.get_serializer(self._with_creators(list(templates)), many=True).data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self._serialize(self.get_object()))

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = create_template(self.team_id, request.user.id, serializer.validated_data)
        self._report_user_action(
            "message_template_created",
            {"template_id": str(template.id), "organization_id": str(self.organization_id)},
        )
        data = self._serialize(template)
        return Response(data, status=status.HTTP_201_CREATED, headers=self.get_success_headers(data))

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        template = self.get_object()
        intent = self._write_intent()
        if is_release(intent):
            released = release_template(
                self.team_id, template.id, require_workflow_editor=self._require_workflow_editor
            )
            self._emit_resource_edited(released)
            return Response(self._serialize(released))
        if is_adoption(intent):
            return self._adopt(template, intent)
        check_template_key_write(template, intent)
        serializer = self.get_serializer(self._with_creators([template])[0], data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            updated = save_template_fields(
                self.team_id,
                template.id,
                serializer.validated_data,
                intent=intent,
                user_id=self._actor_id(),
                require_workflow_editor=self._require_workflow_editor,
            )
        except TransactionalEmailError as e:
            raise TransactionalEmailRejected(e) from None
        self._emit_resource_edited(updated)
        return Response(self._serialize(updated))

    def _adopt(self, template: MessageTemplateRow, intent: TemplateWriteIntent) -> Response:
        key = intent.payload["key"]
        refused = invalid_template_key(key)
        if refused is not None:
            return Response(TemplateErrorSerializer(refused).data, status=status.HTTP_400_BAD_REQUEST)
        adopted = adopt_template(
            self.team_id, template.id, key, intent=intent, require_workflow_editor=self._require_workflow_editor
        )
        self._emit_resource_edited(adopted)
        self._report_user_action("message template adopted", {"template_id": str(adopted.id)})
        return Response(self._serialize(adopted))

    def _report_user_action(self, event: str, properties: dict[str, Any]) -> None:
        # report_user_action injects source and MCP-client properties from the request, so a change from the
        # visual editor and one from the agent count in the same metric. Capture must never break the request.
        try:
            report_user_action(
                self.request.user,
                event,
                {"team_id": str(self.team_id), **properties},
                team=self.team,
                # Without this the event groups by the person's current organization, which can differ
                # from the route's when they belong to more than one.
                organization=self.organization,
                request=self.request,
            )
        except Exception as e:
            logger.warning("Failed to capture message template usage event", error=str(e))

    def _actor_id(self) -> int | None:
        return self.request.user.id if self.request.user.is_authenticated else None

    def _emit_resource_edited(self, instance: MessageTemplateRow) -> None:
        # Realtime "edited elsewhere" signal so an open editor can refresh instead of overwriting a write
        # from another channel (UI/MCP/API). Fires for every channel; the frontend drops its own echo by
        # comparing updated_at. Transient, so no inbox notification. The write is already committed when
        # this runs, so a publish failure must not turn a saved template into an error response.
        try:
            publish_resource_edited(
                team=self.team,
                resource_type="MessageTemplate",
                resource_id=str(instance.id),
                updated_at=instance.updated_at.isoformat(),
                actor_user_id=getattr(self.request.user, "id", None),
                ac_resource_type=self.scope_object,
            )
        except Exception as e:
            logger.warning("Failed to publish message template edited event", error=str(e))

    @extend_schema(
        request=DesignPatchSerializer,
        responses={200: MessageTemplateSerializer, 403: MANAGED_BY_CODE_RESPONSE},
        parameters=[TEMPLATE_ID_PARAMETER],
    )
    @action(detail=True, methods=["PATCH"])
    def design(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Surgical design editing: apply a small, id-addressed op list to the stored Unlayer design instead
        # of re-transmitting the whole design JSON. Reads, applies, validates, re-renders, and saves
        # atomically so a rejected batch leaves the template untouched (and concurrent visual-editor saves
        # can't interleave).

        # Authorize + team-scope via the normal lookup, then re-read FOR UPDATE inside the transaction.
        template = self.get_object()

        op_serializer = DesignPatchSerializer(data=request.data)
        op_serializer.is_valid(raise_exception=True)
        operations = op_serializer.validated_data["operations"]

        def apply_operations(content: dict[str, Any]) -> dict[str, Any]:
            email = content.get("email") or {}
            design = email.get("design")
            if not isinstance(design, dict):
                raise serializers.ValidationError(
                    {
                        "design": "This template has no editable design JSON to patch. Set content.email.design "
                        "with a full update first, then use surgical operations."
                    }
                )

            new_design = apply_design_operations(design, operations)
            for warning in validate_design(new_design):
                logger.info("email_template_design_warning", warning=warning, template_id=str(template.id))

            email["design"] = new_design
            # Drop html so the serializer re-renders it from the patched design (its design->html path).
            email.pop("html", None)
            content["email"] = email

            serializer = self.get_serializer(
                self._with_creators([template])[0], data={"content": content}, partial=True
            )
            serializer.is_valid(raise_exception=True)
            return serializer.validated_data["content"]

        try:
            saved = save_template_content(
                self.team_id,
                template.id,
                apply_operations,
                intent=self._write_intent(),
                user_id=self._actor_id(),
                require_workflow_editor=self._require_workflow_editor,
            )
        except TransactionalEmailError as e:
            raise TransactionalEmailRejected(e) from None

        self._emit_resource_edited(saved)
        return Response(self._serialize(saved))

    @validated_request(
        SendTransactionalEmailSerializer,
        responses={
            202: OpenApiResponse(response=SendTransactionalEmailResponseSerializer, description="Email queued"),
            400: OpenApiResponse(
                description="The template isn't transactional or its email is paused, or the recipient can't be used"
            ),
            404: OpenApiResponse(description="Template not found"),
            429: OpenApiResponse(description="Rate limited, or the project is over its email quota"),
            503: OpenApiResponse(description="The email pipeline did not confirm the send"),
        },
        summary="Send a transactional email",
        description=(
            "Send one transactional email from this template to one recipient. The template must be made "
            "transactional first. `message_data` fills the template's `{{ variables.* }}` placeholders. "
            "Transactional emails skip opt-outs and frequency caps."
        ),
        parameters=[TEMPLATE_ID_PARAMETER],
    )
    @action(detail=True, methods=["POST"], pagination_class=None)
    def send(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()

        queued = self._send_transactional_email(
            request,
            self.get_object(),
            request.validated_data,
            usage={"addressed_by": "url_id", "hash_state": ContentHashState.NONE},
        )
        return Response(SendTransactionalEmailResponseSerializer(queued).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        request=UploadTemplateSerializer,
        responses={
            200: OpenApiResponse(
                response=UploadTemplateResponseSerializer,
                description="The template was updated, is unchanged, or newer content superseded the upload",
            ),
            201: OpenApiResponse(response=UploadTemplateResponseSerializer, description="The template was created"),
            400: OpenApiResponse(
                response=TemplateErrorSerializer,
                description="The key or a field is invalid, the template can't be sent, or there is no verified "
                "default sender",
            ),
            404: OpenApiResponse(description="The transactional email API is not enabled for this project"),
            429: OpenApiResponse(description="Rate limited"),
        },
        summary="Upload a template by key",
        description=(
            "Create or update the email template with this key from HTML, for templates kept as files in a "
            "repository. The first upload creates the template and makes it transactional with the project's "
            "default verified sender. A later upload publishes changed content at once, and answers `unchanged` "
            "when the content is the same. With `if_not_superseded`, an upload of content that newer content "
            "already replaced changes nothing and answers `superseded`. An upload keeps the template's sender and never turns a paused "
            "template back on."
        ),
        parameters=[TEMPLATE_KEY_PARAMETER],
    )
    @action(detail=False, methods=["PUT"], url_path=r"by_key/(?P<key>[^/]+)", pagination_class=None)
    def upload(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()
        refused = invalid_template_key(key)
        body = UploadTemplateSerializer(data=request.data)
        if refused is None and not body.is_valid():
            refused = invalid_request(
                body.errors, why="An upload needs a name, a subject and HTML, each as a string.", retry="upload again"
            )
        if refused is not None:
            self._report_template_upload(request, {"result": "rejected", "error_code": refused.code})
            return Response(TemplateErrorSerializer(refused).data, status=status.HTTP_400_BAD_REQUEST)

        try:
            uploaded = upload_template(
                self.team_id,
                self._template_upload(key, body.validated_data),
                user_id=self._actor_id(),
                require_workflow_editor=self._require_workflow_editor,
                require_workflow_create=self._require_workflow_create,
            )
        except TransactionalEmailError as e:
            self._report_template_upload(request, {"result": "rejected", "error_code": e.code})
            raise TransactionalEmailRejected(e) from None

        self._report_template_upload(request, {"result": uploaded.result, "template_id": str(uploaded.template.id)})
        if uploaded.result in (TemplateUploadResult.CREATED, TemplateUploadResult.UPDATED):
            self._emit_resource_edited(uploaded.template)
        created = uploaded.result == TemplateUploadResult.CREATED
        return Response(
            UploadTemplateResponseSerializer(self._upload_response(uploaded)).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @staticmethod
    def _template_upload(key: str, data: dict[str, Any]) -> TemplateUpload:
        source = data.get("source")
        return TemplateUpload(
            key=key,
            name=data["name"],
            subject=data["subject"],
            html=data["html"],
            text=data.get("text", ""),
            preheader=data.get("preheader", ""),
            # Wraps the html in one custom HTML block, so the visual editor can open the template.
            design=build_html_wrap_design(data["html"]),
            source=TemplateSource(repository=source.get("repository"), path=source.get("path"), ref=source.get("ref"))
            if source
            else None,
            if_not_superseded=data["if_not_superseded"],
        )

    @staticmethod
    def _upload_response(uploaded: UploadedTemplate) -> dict[str, Any]:
        template = uploaded.template
        return {
            "id": template.id,
            "key": template.key,
            "result": uploaded.result,
            "content_hash": template.content_hash,
            "managed_by": template.managed_by,
            "source": {
                "repository": template.source_repository,
                "path": template.source_path,
                "ref": template.source_ref,
            },
            "transactional_hog_flow_id": template.transactional_hog_flow_id,
        }

    def _require_workflow_create(self) -> None:
        if is_authenticated_via_project_secret_api_key(self.request):
            return
        # Access to one workflow lets a member through the viewset's checks, but an upload can create a new one.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "editor"):
            raise exceptions.PermissionDenied("You need editor access to workflows to upload a new template.")

    def _report_template_upload(self, request: Any, outcome: dict[str, Any]) -> None:
        # report_user_action drops the synthetic user behind a project secret API key, so capture directly.
        try:
            posthoganalytics.capture(
                distinct_id=request.user.distinct_id,
                event="transactional email template uploaded",
                properties={"team_id": self.team_id, "auth_method": self._auth_method(request), **outcome},
                groups=groups(self.organization, self.team),
            )
        except Exception as e:
            logger.warning("Failed to capture transactional email template upload event", error=str(e))

    @validated_request(
        MakeTransactionalSerializer,
        responses={
            200: OpenApiResponse(response=MessageTemplateSerializer, description="The transactional template"),
            400: OpenApiResponse(description="The template can't be sent, or there is no verified sender"),
            404: OpenApiResponse(description="Template not found"),
        },
        summary="Make a template transactional",
        description=(
            "Make this template sendable over the transactional email API. This creates the workflow that sends it, "
            "with its own metrics, run history and versions. Calling it again on a transactional template changes "
            "nothing."
        ),
        parameters=[TEMPLATE_ID_PARAMETER],
    )
    @action(detail=True, methods=["POST"], pagination_class=None)
    def make_transactional(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        self._require_transactional_email_flag()
        template = self.get_object()
        was_transactional = template.transactional_hog_flow_id is not None
        # Access to one workflow lets a member through the viewset's checks, but this can create a new one, also
        # when the linked workflow was deleted.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "editor"):
            raise exceptions.PermissionDenied("You need editor access to workflows to make a template transactional.")
        try:
            make_transactional(
                self.team_id,
                template.id,
                user_id=self._actor_id(),
                from_integration_id=request.validated_data.get("from_integration_id"),
            )
        except TransactionalEmailError as e:
            raise TransactionalEmailRejected(e) from None
        updated = self.get_object()
        if not was_transactional:
            self._emit_resource_edited(updated)
            self._report_user_action("message template made transactional", {"template_id": str(template.id)})
        return Response(self._serialize(updated))
