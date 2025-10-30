from typing import Any

import structlog
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.integration import GitHubIntegration, GitLabIntegration, Integration, LinearIntegration

from products.error_tracking.backend.models import ErrorTrackingExternalReference, ErrorTrackingIssue

logger = structlog.get_logger(__name__)


class ErrorTrackingExternalReferenceIntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = ["id", "kind", "display_name"]
        read_only_fields = ["id", "kind", "display_name"]


class ErrorTrackingExternalReferenceSerializer(serializers.ModelSerializer):
    config = serializers.JSONField(write_only=True)
    issue = serializers.PrimaryKeyRelatedField(write_only=True, queryset=ErrorTrackingIssue.objects.all())
    integration = ErrorTrackingExternalReferenceIntegrationSerializer(read_only=True)
    integration_id = serializers.PrimaryKeyRelatedField(
        write_only=True, queryset=Integration.objects.all(), source="integration"
    )
    external_url = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingExternalReference
        fields = ["id", "integration", "integration_id", "config", "issue", "external_url"]
        read_only_fields = ["external_url"]

    def get_external_url(self, reference: ErrorTrackingExternalReference) -> str:
        external_context: dict[str, str] = reference.external_context or {}
        if reference.integration.kind == Integration.IntegrationKind.LINEAR:
            url_key = LinearIntegration(reference.integration).url_key()
            return f"https://linear.app/{url_key}/issue/{external_context['id']}"
        elif reference.integration.kind == Integration.IntegrationKind.GITHUB:
            org = GitHubIntegration(reference.integration).organization()
            return f"https://github.com/{org}/{external_context['repository']}/issues/{external_context['number']}"
        elif reference.integration.kind == Integration.IntegrationKind.GITLAB:
            gitlab = GitLabIntegration(reference.integration)
            return f"{gitlab.hostname}/{gitlab.project_path}/issues/{external_context['issue_id']}"
        raise ValidationError("Provider not supported")

    def validate(self, data):
        issue = data["issue"]
        integration = data["integration"]
        team = self.context["get_team"]()

        if issue.team_id != team.id:
            raise serializers.ValidationError("Issue does not belong to this team.")

        if integration.team_id != team.id:
            raise serializers.ValidationError("Integration does not belong to this team.")

        return data

    def create(self, validated_data) -> ErrorTrackingExternalReference:
        team = self.context["get_team"]()
        issue: ErrorTrackingIssue = validated_data.get("issue")
        integration: Integration = validated_data.get("integration")

        config: dict[str, Any] = validated_data.pop("config")

        if integration.kind == "github":
            external_context = GitHubIntegration(integration).create_issue(config)
        elif integration.kind == "gitlab":
            external_context = GitLabIntegration(integration).create_issue(config)
        elif integration.kind == "linear":
            external_context = LinearIntegration(integration).create_issue(team.pk, issue.id, config)
        else:
            raise ValidationError("Provider not supported")

        instance = ErrorTrackingExternalReference.objects.create(
            issue=issue,
            integration=integration,
            external_context=external_context,
        )
        return instance


class ErrorTrackingExternalReferenceViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingExternalReference.objects.all()
    serializer_class = ErrorTrackingExternalReferenceSerializer
