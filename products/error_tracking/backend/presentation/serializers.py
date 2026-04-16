from dataclasses import dataclass
from typing import Any, Optional

import posthoganalytics
from drf_spectacular.utils import extend_schema_field
from loginas.utils import is_impersonated_session
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.event_usage import groups
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.integration import (
    GitHubIntegration,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
)

from products.error_tracking.backend import logic
from products.error_tracking.backend.models import (
    ErrorTrackingAssignmentRule,
    ErrorTrackingExternalReference,
    ErrorTrackingGroupingRule,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRelease,
    ErrorTrackingSpikeDetectionConfig,
    ErrorTrackingSpikeEvent,
    ErrorTrackingStackFrame,
    ErrorTrackingSuppressionRule,
    ErrorTrackingSymbolSet,
    sync_issues_to_clickhouse,
)


class ErrorTrackingIssueAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssueAssignment
        fields = ["id", "type"]

    @extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True})
    def get_id(self, obj):
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

    @extend_schema_field(serializers.CharField())
    def get_type(self, obj):
        return "role" if obj.role else "user"


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

    def get_external_url(self, reference: ErrorTrackingExternalReference) -> str:
        external_url = logic.build_external_issue_url(reference)
        if external_url:
            return external_url

        if logic.is_supported_external_issue_provider(reference.integration.kind):
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


class ErrorTrackingAssignmentRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingAssignmentRule
        fields = ["id", "filters", "assignee", "order_key", "disabled_data", "created_at", "updated_at"]
        read_only_fields = ["team_id", "created_at", "updated_at"]

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "type": {"type": "string", "enum": ["user", "role"]},
                "id": {"oneOf": [{"type": "integer"}, {"type": "string", "format": "uuid"}]},
            },
        }
    )
    def get_assignee(self, obj):
        if obj.user_id:
            return {"type": "user", "id": obj.user_id}
        if obj.role_id:
            return {"type": "role", "id": obj.role_id}
        return None


class ErrorTrackingGroupingRuleSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()
    issue = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingGroupingRule
        fields = ["id", "filters", "assignee", "issue", "order_key", "disabled_data", "created_at", "updated_at"]
        read_only_fields = ["team_id", "created_at", "updated_at"]

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "type": {"type": "string", "enum": ["user", "role"]},
                "id": {"oneOf": [{"type": "integer"}, {"type": "string", "format": "uuid"}]},
            },
        }
    )
    def get_assignee(self, obj):
        if obj.user_id:
            return {"type": "user", "id": obj.user_id}
        if obj.role_id:
            return {"type": "role", "id": obj.role_id}
        return None

    @extend_schema_field(
        serializers.DictField(child=serializers.CharField(), allow_null=True, help_text="Issue linked to this rule")
    )
    def get_issue(self, obj) -> Optional[dict]:
        issue_map = self.context.get("issue_map", {})
        issue = issue_map.get(str(obj.id))
        if issue:
            return {"id": str(issue.id), "name": issue.name}
        return None


class ErrorTrackingIssuePreviewSerializer(serializers.ModelSerializer):
    first_seen = serializers.DateTimeField()
    assignee = ErrorTrackingIssueAssignmentSerializer(source="assignment")

    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "status", "name", "description", "first_seen", "assignee"]


class ErrorTrackingIssueFullSerializer(serializers.ModelSerializer):
    first_seen = serializers.DateTimeField()
    assignee = ErrorTrackingIssueAssignmentSerializer(source="assignment")
    external_issues = ErrorTrackingExternalReferenceSerializer(many=True)
    cohort = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "status", "name", "description", "first_seen", "assignee", "external_issues", "cohort"]

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
            },
        }
    )
    def get_cohort(self, instance):
        first_cohort = instance.cohorts.filter(cohort__deleted=False).first()
        return {"id": first_cohort.cohort_id, "name": first_cohort.cohort.name} if first_cohort is not None else None

    def update(self, instance, validated_data):
        team = instance.team
        status_after = validated_data.get("status")
        status_before = instance.status
        status_updated = "status" in validated_data and status_after != status_before

        name_after = validated_data.get("name")
        name_before = instance.name
        name_updated = "name" in validated_data and name_after != name_before

        updated_instance = super().update(instance, validated_data)

        changes = []
        if status_updated:
            changes.append(
                Change(
                    type="ErrorTrackingIssue",
                    field="status",
                    before=status_before,
                    after=status_after,
                    action="changed",
                )
            )
        if name_updated:
            changes.append(
                Change(type="ErrorTrackingIssue", field="name", before=name_before, after=name_after, action="changed")
            )

        if changes:
            log_activity(
                organization_id=team.organization.id,
                team_id=team.id,
                user=self.context["request"].user,
                was_impersonated=is_impersonated_session(self.context["request"]),
                item_id=str(updated_instance.id),
                scope="ErrorTrackingIssue",
                activity="updated",
                detail=Detail(
                    name=instance.name,
                    changes=changes,
                ),
            )
            sync_issues_to_clickhouse(issue_ids=[updated_instance.id], team_id=team.id)

        return updated_instance


class ErrorTrackingIssueMergeRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="IDs of the issues to merge into the current issue.",
    )


class ErrorTrackingIssueMergeResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(help_text="Whether the merge completed successfully.")


class ErrorTrackingReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingRelease
        fields = ["id", "hash_id", "team_id", "created_at", "metadata", "version", "project"]
        read_only_fields = ["team_id"]


class ErrorTrackingSpikeDetectionConfigSerializer(serializers.ModelSerializer):
    snooze_duration_minutes = serializers.IntegerField(min_value=1)
    multiplier = serializers.IntegerField(min_value=1)
    threshold = serializers.IntegerField(min_value=1)

    class Meta:
        model = ErrorTrackingSpikeDetectionConfig
        fields = ["snooze_duration_minutes", "multiplier", "threshold"]


class ErrorTrackingSpikeEventIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "name", "description"]
        read_only_fields = fields


class ErrorTrackingSpikeEventSerializer(serializers.ModelSerializer):
    issue = ErrorTrackingSpikeEventIssueSerializer(read_only=True)

    class Meta:
        model = ErrorTrackingSpikeEvent
        fields = [
            "id",
            "issue",
            "detected_at",
            "computed_baseline",
            "current_bucket_value",
        ]
        read_only_fields = fields


class ErrorTrackingStackFrameSerializer(serializers.ModelSerializer):
    symbol_set_ref = serializers.CharField(source="symbol_set.ref", default=None)
    release = ErrorTrackingReleaseSerializer(source="symbol_set.release", read_only=True)
    raw_id = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingStackFrame
        fields = ["id", "raw_id", "created_at", "contents", "resolved", "context", "symbol_set_ref", "release"]

    @extend_schema_field(serializers.CharField(help_text="Raw frame ID in 'hash/part' format"))
    def get_raw_id(self, obj):
        return obj.raw_id + "/" + str(obj.part)


class ErrorTrackingSuppressionRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSuppressionRule
        fields = ["id", "filters", "order_key", "disabled_data", "sampling_rate", "created_at", "updated_at"]
        read_only_fields = ["team_id", "created_at", "updated_at"]


class ErrorTrackingSymbolSetSerializer(serializers.ModelSerializer):
    release = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingSymbolSet
        fields = ["id", "ref", "team_id", "created_at", "last_used", "storage_ptr", "failure_reason", "release"]
        read_only_fields = ["team_id"]

    @extend_schema_field(serializers.DictField(allow_null=True, help_text="Release associated with this symbol set"))
    def get_release(self, obj):
        if obj.release:
            return ErrorTrackingReleaseSerializer(obj.release).data
        return None


@dataclass
class SymbolSetUpload:
    chunk_id: str
    release_id: str | None
    content_hash: str | None


class ErrorTrackingSymbolSetUploadSerializer(serializers.Serializer):
    chunk_id = serializers.CharField()
    release_id = serializers.CharField(allow_null=True, default=None)
    content_hash = serializers.CharField(allow_null=True, default=None)
