from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.workflows.backend.facade.sandbox_email import (
    ADOPTION_UNAVAILABLE,
    provision_sandbox_sender,
    sandbox_sender_status,
)


class WorkflowEmailSandboxStatusSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the project's sandbox sender, which an email step can use. Null until the sender is set up.",
    )
    from_address = serializers.CharField(
        allow_blank=True,
        help_text="The address sandbox emails come from. Blank when sandbox sending isn't configured.",
    )
    display_name = serializers.CharField(help_text="The sender name sandbox emails show, such as 'Acme via PostHog'.")
    organization_blocked = serializers.BooleanField(
        help_text="Whether PostHog has stopped this organization from using the sandbox sender."
    )
    adoption_enabled = serializers.BooleanField(
        help_text="Whether the project can add new sandbox email steps. Steps it already has keep working either way."
    )


class WorkflowEmailSandboxProvisionSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="ID of the project's sandbox sender.")


class WorkflowEmailSandboxViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """The sandbox sender, which sends workflow email to organization members before a domain is verified."""

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
        user = self._user()
        status = sandbox_sender_status(self.team, user)
        if not status.adoption_enabled:
            raise exceptions.PermissionDenied(ADOPTION_UNAVAILABLE)
        if status.organization_blocked:
            raise exceptions.PermissionDenied(
                "This organization can't use the sandbox sender. Verify a domain to send email from workflows."
            )
        row = provision_sandbox_sender(self.team, user)
        return Response(WorkflowEmailSandboxProvisionSerializer({"integration_id": row.id}).data)

    def _user(self) -> User:
        user = self.request.user
        if not isinstance(user, User):
            raise exceptions.NotAuthenticated()
        return user
