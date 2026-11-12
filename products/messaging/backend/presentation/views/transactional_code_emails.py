from collections.abc import Collection
from dataclasses import asdict
from typing import Any
from uuid import UUID

from django.core.validators import URLValidator

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.tag import tagify

from products.messaging.backend.facade.code_emails import (
    SOURCE_URL_MAX_LENGTH,
    get_code_email,
    list_code_emails,
    update_code_email,
)
from products.messaging.backend.facade.contracts import (
    CodeEmailSourceOrigin,
    CodeManagedEmail,
    CodeManagedEmailNotFound,
)
from products.messaging.backend.presentation.views.message_templates import require_email_status_read
from products.workflows.backend.facade.api import (
    WorkflowAccessDenied,
    WorkflowNotFound,
    get_viewable_workflow_ids,
    get_workflow_access_levels,
)
from products.workflows.backend.facade.workflows import get_workflow_ref

# Each tag costs get_or_create round trips when it is saved, so cap the list.
_MAX_TAGS = 10
_MAX_TAG_LENGTH = 255  # Tag.name column limit.

CODE_EMAIL_ID_PARAMETER = OpenApiParameter(
    name="id", type=OpenApiTypes.UUID, location=OpenApiParameter.PATH, description="The code email's ID."
)


class CodeEmailSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The code email's ID.")
    key = serializers.CharField(help_text="The `template_key` your code sends under. Each key is one email.")
    hog_flow_id = serializers.UUIDField(help_text="The hidden workflow that sends this key's emails.")
    description = serializers.CharField(help_text="What the email is for. Empty when nobody added one.")
    tags = serializers.ListField(child=serializers.CharField(), help_text="Tags for organizing transactional emails.")
    sensitive = serializers.BooleanField(
        help_text="True when PostHog keeps no copy of each sent email's body and doesn't track link clicks."
    )
    source_url = serializers.CharField(
        allow_null=True, help_text="A link to the file in your repository that sends this email. Null when unlinked."
    )
    source_origin = serializers.ChoiceField(
        choices=CodeEmailSourceOrigin.choices,
        read_only=True,
        allow_null=True,
        help_text="How `source_url` was set: `manual` when a person linked or unlinked it, `detected` when PostHog "
        "found the file in a connected GitHub repository. Setting `source_url` makes it `manual`. Null when no link "
        "was ever set or cleared.",
    )
    created_at = serializers.DateTimeField(help_text="When your code first sent under this key.")
    user_access_level = serializers.CharField(
        allow_null=True,
        help_text="Your access level to this email's workflow, such as `viewer` or `editor`. Editing the description, "
        "the tags or the source file needs `editor`.",
    )


class CodeEmailUpdateSerializer(serializers.Serializer):
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=1000, help_text="What the email is for."
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=_MAX_TAG_LENGTH),
        required=False,
        max_length=_MAX_TAGS,
        help_text="Tags for organizing transactional emails. Replaces the current tags. Send an empty list to remove "
        "them all.",
    )
    source_url = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=SOURCE_URL_MAX_LENGTH,
        validators=[URLValidator(schemes=["http", "https"])],
        help_text="A link to the file in your repository that sends this email, such as a GitHub or GitLab file "
        "link. Must start with http:// or https://. Send null or an empty string to unlink it.",
    )

    def validate_source_url(self, source_url: str | None) -> str | None:
        return source_url or None

    def validate_tags(self, tags: list[str]) -> list[str]:
        # Lowercasing can lengthen a string, so the stored name is checked, not the submitted one.
        if any(len(tagify(tag)) > _MAX_TAG_LENGTH for tag in tags):
            raise serializers.ValidationError(f"A tag may be at most {_MAX_TAG_LENGTH} characters once lowercased.")
        return tags


class TransactionalCodeEmailViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["partial_update"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        require_email_status_read(self.team)

    def _viewable_workflow_ids(self, workflow_ids: Collection[str]) -> set[str]:
        # A code email inherits the access rules of its hidden workflow.
        return get_viewable_workflow_ids(
            team_id=self.team_id, user_access_control=self.user_access_control, workflow_ids=workflow_ids
        )

    def _rows(self, emails: list[CodeManagedEmail]) -> list[dict[str, Any]]:
        levels = get_workflow_access_levels(
            team_id=self.team_id,
            user_access_control=self.user_access_control,
            workflow_ids=[str(email.hog_flow_id) for email in emails],
        )
        return [asdict(email) | {"user_access_level": levels.get(str(email.hog_flow_id))} for email in emails]

    def _code_email_id(self, pk: str | None) -> UUID:
        try:
            return UUID(str(pk))
        except ValueError:
            raise exceptions.NotFound()

    @extend_schema(
        responses={200: CodeEmailSerializer(many=True)},
        summary="List emails sent from code",
        description="List the emails your code sends under a `template_key` that no template owns, newest first.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        emails = list_code_emails(self.team_id, viewable_workflows=self._viewable_workflow_ids)
        return Response(CodeEmailSerializer(self._rows(emails), many=True).data)

    @extend_schema(
        parameters=[CODE_EMAIL_ID_PARAMETER],
        responses={200: CodeEmailSerializer, 404: OpenApiResponse(description="No such code email in this project.")},
        summary="Get an email sent from code",
    )
    def retrieve(self, request: Request, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            email = get_code_email(
                self.team_id, self._code_email_id(pk), viewable_workflows=self._viewable_workflow_ids
            )
        except CodeManagedEmailNotFound:
            raise exceptions.NotFound()
        return Response(CodeEmailSerializer(self._rows([email])[0]).data)

    @validated_request(
        request_serializer=CodeEmailUpdateSerializer,
        responses={
            200: OpenApiResponse(response=CodeEmailSerializer),
            403: OpenApiResponse(description="You need editor access to this email's workflow."),
            404: OpenApiResponse(description="No such code email in this project."),
        },
        parameters=[CODE_EMAIL_ID_PARAMETER],
        summary="Update an email sent from code",
        description="Change the description, the tags or the linked source file. The content always comes from your "
        "code, so it can't change here.",
    )
    def partial_update(self, request: ValidatedRequest, *args: Any, pk: str | None = None, **kwargs: Any) -> Response:
        code_email_id = self._code_email_id(pk)
        viewable = self._viewable_workflow_ids
        try:
            self._require_workflow_editor(get_code_email(self.team_id, code_email_id, viewable_workflows=viewable))
            email = update_code_email(self.team_id, code_email_id, request.validated_data, viewable_workflows=viewable)
        except (CodeManagedEmailNotFound, WorkflowNotFound):
            raise exceptions.NotFound()
        return Response(CodeEmailSerializer(self._rows([email])[0]).data)

    def _require_workflow_editor(self, email: CodeManagedEmail) -> None:
        try:
            get_workflow_ref(
                team_id=self.team_id,
                workflow_id=email.hog_flow_id,
                user_access_control=self.user_access_control,
                required_level="editor",
            )
        except WorkflowAccessDenied:
            raise exceptions.PermissionDenied("You need editor access to this email's workflow.") from None
