from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.workflows.backend.facade.sandbox_email import (
    SandboxSenderUnavailable,
    sandbox_sender_status,
    set_up_sandbox_sender,
)


class WorkflowEmailSandboxStatusSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the project's PostHog test sender, which an email step can use. Null until the sender is set up.",
    )
    from_address = serializers.CharField(
        allow_blank=True,
        help_text="The address the PostHog test sender sends from. Blank when the PostHog test sender isn't configured.",
    )
    display_name = serializers.CharField(
        help_text="The sender name emails from the PostHog test sender show, such as 'Acme via PostHog'."
    )
    organization_blocked = serializers.BooleanField(
        help_text="Whether PostHog has stopped this organization from using the PostHog test sender."
    )
    adoption_enabled = serializers.BooleanField(
        help_text="Whether the project can add new PostHog test sender steps. Steps it already has keep working either way."
    )


class WorkflowEmailSandboxProvisionSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="ID of the project's PostHog test sender.")


class WorkflowEmailSandboxViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """The PostHog test sender, which sends workflow email to organization members before a domain is verified."""

    scope_object = "hog_flow"
    requires_resource_level_access = True
    scope_object_write_actions = ["status", "provision"]

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        return ["hog_flow:write"]

    @extend_schema(operation_id="workflow_email_sandbox_status", responses={200: WorkflowEmailSandboxStatusSerializer})
    @action(detail=False, methods=["get"])
    def status(self, request: Request, **kwargs: Any) -> Response:
        return Response(WorkflowEmailSandboxStatusSerializer(sandbox_sender_status(self.team, self._user())).data)

    @extend_schema(
        operation_id="workflow_email_sandbox_provision",
        request=None,
        responses={200: WorkflowEmailSandboxProvisionSerializer},
    )
    @action(detail=False, methods=["post"])
    def provision(self, request: Request, **kwargs: Any) -> Response:
        try:
            row = set_up_sandbox_sender(self.team, self._user())
        except SandboxSenderUnavailable as error:
            raise exceptions.PermissionDenied(str(error))
        return Response(WorkflowEmailSandboxProvisionSerializer({"integration_id": row.id}).data)

    def _user(self) -> User:
        user = self.request.user
        if not isinstance(user, User):
            raise exceptions.NotAuthenticated()
        return user
