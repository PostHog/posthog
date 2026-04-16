from typing import Any

from django.apps import apps

import posthoganalytics
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.event_usage import groups
from posthog.models.integration import (
    GitHubIntegration,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
)

ErrorTrackingExternalReference = apps.get_model("error_tracking", "ErrorTrackingExternalReference")
ErrorTrackingIssue = apps.get_model("error_tracking", "ErrorTrackingIssue")
ErrorTrackingIssueFingerprintV2 = apps.get_model("error_tracking", "ErrorTrackingIssueFingerprintV2")

SUPPORTED_EXTERNAL_ISSUE_PROVIDERS = frozenset(
    {
        Integration.IntegrationKind.LINEAR,
        Integration.IntegrationKind.GITHUB,
        Integration.IntegrationKind.GITLAB,
        Integration.IntegrationKind.JIRA,
    }
)


def is_supported_external_issue_provider(kind: str) -> bool:
    return kind in SUPPORTED_EXTERNAL_ISSUE_PROVIDERS


def build_external_issue_url(reference: Any) -> str:
    external_context: dict[str, str] = reference.external_context or {}
    integration = reference.integration

    if integration.kind == Integration.IntegrationKind.LINEAR:
        issue_id = external_context.get("id")
        if not issue_id:
            return ""
        url_key = LinearIntegration(integration).url_key()
        return f"https://linear.app/{url_key}/issue/{issue_id}"

    if integration.kind == Integration.IntegrationKind.GITHUB:
        repository = external_context.get("repository")
        number = external_context.get("number")
        if not repository or not number:
            return ""
        org = GitHubIntegration(integration).organization()
        return f"https://github.com/{org}/{repository}/issues/{number}"

    if integration.kind == Integration.IntegrationKind.GITLAB:
        issue_id = external_context.get("issue_id")
        if not issue_id:
            return ""
        gitlab = GitLabIntegration(integration)
        return f"{gitlab.hostname}/{gitlab.project_path}/issues/{issue_id}"

    if integration.kind == Integration.IntegrationKind.JIRA:
        issue_key = external_context.get("key")
        if not issue_key:
            return ""
        jira = JiraIntegration(integration)
        return f"{jira.site_url()}/browse/{issue_key}"

    return ""


class ErrorTrackingExternalReferenceIntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Integration
        fields = ["id", "kind", "display_name"]
        read_only_fields = ["id", "kind", "display_name"]


class ErrorTrackingFingerprintSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingIssueFingerprintV2
        fields = ["fingerprint", "issue_id", "created_at"]


class ErrorTrackingExternalReferenceSerializer(serializers.ModelSerializer):
    config = serializers.JSONField(write_only=True)
    issue = TeamScopedPrimaryKeyRelatedField(write_only=True, queryset=ErrorTrackingIssue.objects.all())
    integration = ErrorTrackingExternalReferenceIntegrationSerializer(read_only=True)
    integration_id = TeamScopedPrimaryKeyRelatedField(
        write_only=True, queryset=Integration.objects.all(), source="integration"
    )
    external_url = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingExternalReference
        fields = ["id", "integration", "integration_id", "config", "issue", "external_url"]
        read_only_fields = ["external_url"]

    def get_external_url(self, reference: Any) -> str:
        external_url = build_external_issue_url(reference)
        if external_url:
            return external_url

        if is_supported_external_issue_provider(reference.integration.kind):
            raise ValidationError("Missing required external context fields")

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

    def create(self, validated_data) -> Any:
        team = self.context["get_team"]()
        issue = validated_data.get("issue")
        integration = validated_data.get("integration")

        config: dict[str, Any] = validated_data.pop("config")

        if integration.kind == "github":
            external_context = GitHubIntegration(integration).create_issue(config)
        elif integration.kind == "gitlab":
            external_context = GitLabIntegration(integration).create_issue(config)
        elif integration.kind == "linear":
            external_context = LinearIntegration(integration).create_issue(team.pk, issue.id, config)
        elif integration.kind == "jira":
            external_context = JiraIntegration(integration).create_issue(config)
        else:
            raise ValidationError("Provider not supported")

        instance = ErrorTrackingExternalReference.objects.create(
            issue=issue,
            integration=integration,
            external_context=external_context,
        )

        posthoganalytics.capture(
            "error_tracking_external_issue_created",
            groups=groups(team.organization, team),
            properties={
                "issue_id": issue.id,
                "integration_kind": integration.kind,
            },
        )

        return instance
