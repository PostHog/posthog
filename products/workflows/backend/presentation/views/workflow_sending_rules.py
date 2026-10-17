from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.project import update_team_workflows_config
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.organization import OrganizationMembership

from products.workflows.backend.facade.enums import EMAIL_TRACKING_CONSENT_MODE_CHOICES
from products.workflows.backend.facade.team_extension import TeamWorkflowsConfig


class WorkflowSendingRulesSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(
        source="team_id", read_only=True, help_text="The project these sending rules belong to."
    )
    expected_project_id = serializers.IntegerField(
        write_only=True,
        required=False,
        help_text="Optional. The project_id from the rules being changed. The update is rejected when it does not "
        "match the current project, so a change never lands in a project the user did not look at.",
    )
    marketing_frequency_cap_max_messages = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=1000,
        help_text="The most marketing messages one person gets in the window, across all workflows and broadcasts. "
        "Set it together with marketing_frequency_cap_window_days, or set both to null to turn the cap off. "
        "Transactional messages are never capped. The recommended cap is 1 message every 2 days.",
    )
    marketing_frequency_cap_window_days = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=30,
        help_text="The length of the rolling frequency cap window, in days. Set it together with "
        "marketing_frequency_cap_max_messages, or set both to null to turn the cap off.",
    )
    email_tracking_consent_mode = serializers.ChoiceField(
        choices=EMAIL_TRACKING_CONSENT_MODE_CHOICES,
        required=False,
        help_text="Whether tracking opens and clicks on marketing email needs the recipient's consent. "
        "'off' follows each email step's own setting, 'opt_out' tracks unless the recipient objected, and 'opt_in' "
        "tracks only recipients who consented. Transactional email is never affected.",
    )
    capture_workflows_engagement_events = serializers.BooleanField(
        required=False,
        help_text="Capture email sends, opens, clicks and bounces as PostHog events, so they can be used in insights "
        "and funnels. These events count toward the project's event usage.",
    )


class WorkflowSendingRulesViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """The project-wide rules every workflow and broadcast follows when it sends a message."""

    scope_object = "project"
    scope_object_read_actions = ["current"]
    scope_object_write_actions = ["update_current"]

    @extend_schema(operation_id="workflow_sending_rules_retrieve", responses={200: WorkflowSendingRulesSerializer})
    @action(detail=False, methods=["get"])
    def current(self, request: Request, **kwargs: Any) -> Response:
        return Response(self._rules())

    @extend_schema(
        operation_id="workflow_sending_rules_partial_update",
        request=WorkflowSendingRulesSerializer,
        responses={200: WorkflowSendingRulesSerializer},
    )
    @current.mapping.patch
    def update_current(self, request: Request, **kwargs: Any) -> Response:
        # Matches the admin-only rule on workflows_config in project settings.
        level = self.user_permissions.team(self.team).effective_membership_level
        if level is None or level < OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("Only project admins can change sending rules.")
        payload = WorkflowSendingRulesSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        changes = dict(payload.validated_data)
        expected_project_id = changes.pop("expected_project_id", None)
        if expected_project_id is not None and expected_project_id != self.team.id:
            raise ValidationError(
                {"expected_project_id": "These sending rules belong to another project. Switch back to it first."}
            )
        update_team_workflows_config(
            self.team,
            changes,
            context={"request": request, "user_access_control": self.user_access_control},
        )
        return Response(self._rules())

    def _rules(self) -> dict[str, Any]:
        # Read the row fresh: `Team.workflows_config` is a cached_property and can hold values from before an update.
        config = TeamWorkflowsConfig.objects.filter(team_id=self.team.id).first() or TeamWorkflowsConfig(
            team_id=self.team.id
        )
        return WorkflowSendingRulesSerializer(config).data
