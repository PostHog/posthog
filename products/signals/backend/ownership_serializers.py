from __future__ import annotations

from uuid import UUID

from rest_framework import serializers

from products.access_control.backend.facade.api import get_routing_roles
from products.signals.backend.models import (
    SignalDomainPreference,
    SignalProductDomain,
    SignalReportRouting,
    SignalRoutingBatch,
    SignalRoutingBatchChange,
    SignalRoutingProposal,
)


class SignalProductDomainSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Stable product-domain ID. Renaming preserves personal rules.")
    name = serializers.CharField(max_length=100, help_text="Name of the capability that needs attention.")
    description = serializers.CharField(
        max_length=4000, allow_blank=True, help_text="Responsibility boundaries, including examples and exclusions."
    )
    owning_role_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Role representing the current responsible team, in this project's organization.",
    )
    owning_role_name = serializers.CharField(
        source="owning_role.name", read_only=True, allow_null=True, help_text="Responsible team's current display name."
    )
    repository = serializers.CharField(
        required=False,
        max_length=200,
        allow_blank=True,
        help_text="Optional owner/repository used to ground this domain's code locations.",
    )
    code_paths = serializers.ListField(
        child=serializers.CharField(max_length=500),
        max_length=100,
        required=False,
        help_text="Optional repository paths or patterns supporting domain classification.",
    )
    import_state = serializers.JSONField(
        read_only=True, help_text="Repository import provenance, last refresh, and fields preserved after human edits."
    )
    archived = serializers.BooleanField(
        required=False, help_text="Archived domains retain routing history and preferences."
    )
    revision = serializers.IntegerField(
        read_only=True, help_text="Definition revision used to detect stale routing and previews."
    )

    class Meta:
        model = SignalProductDomain
        fields = [
            "id",
            "name",
            "description",
            "owning_role_id",
            "owning_role_name",
            "repository",
            "code_paths",
            "archived",
            "revision",
            "import_state",
        ]

    def validate_owning_role_id(self, value: UUID | None) -> UUID | None:
        if value is not None and not any(
            role.id == value for role in get_routing_roles(team_id=self.context["team_id"])
        ):
            raise serializers.ValidationError("Choose a team from this project's organization.")
        return value

    def validate_name(self, value: str) -> str:
        existing = SignalProductDomain.objects.for_team(self.context["team_id"]).filter(name=value)
        if self.instance is not None:
            existing = existing.exclude(id=self.instance.id)
        if existing.exists():
            raise serializers.ValidationError("This product domain already exists. Choose another name.")
        return value


class SignalRoutingRoleSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Organization role ID representing a responsible team.")
    name = serializers.CharField(help_text="Team display name.")
    is_member = serializers.BooleanField(
        help_text="Whether the current user belongs to this team and can access the project."
    )


class SignalReportRoutingSerializer(serializers.ModelSerializer):
    domain = SignalProductDomainSerializer(
        read_only=True, allow_null=True, help_text="Primary product domain; null when unclassified."
    )
    owning_role_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Persistent responsible team assignment."
    )
    owning_role_name = serializers.CharField(
        source="owning_role.name", read_only=True, allow_null=True, help_text="Responsible team's current name."
    )
    explanation = serializers.CharField(
        read_only=True, allow_blank=True, help_text="Evidence supporting the routing decision."
    )
    confidence = serializers.FloatField(
        read_only=True, allow_null=True, help_text="Classifier score, not calibrated accuracy."
    )
    classifier_version = serializers.CharField(
        read_only=True, allow_blank=True, help_text="Classifier or definition version used for the decision."
    )
    human_override = serializers.BooleanField(
        read_only=True, help_text="Whether automatic classification must preserve this correction."
    )
    accepted = serializers.BooleanField(
        read_only=True, help_text="Only accepted primary domains affect personal domain rules."
    )

    class Meta:
        model = SignalReportRouting
        extra_kwargs = {"source": {"read_only": True, "help_text": "Where this routing decision came from."}}
        fields = [
            "domain",
            "owning_role_id",
            "owning_role_name",
            "source",
            "explanation",
            "confidence",
            "classifier_version",
            "human_override",
            "accepted",
        ]


class SignalRoutingCorrectionSerializer(serializers.Serializer):
    domain_id = serializers.UUIDField(
        allow_null=True, help_text="Primary product domain in this project, or null to leave it unclassified."
    )
    owning_role_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Responsible team override. When omitted, use the domain's current team.",
    )
    explanation = serializers.CharField(
        max_length=500, allow_blank=True, required=False, default="", help_text="Why this domain or team owns the work."
    )


class SignalDomainPreferenceSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Personal routing preference ID.")
    domain = SignalProductDomainSerializer(read_only=True, help_text="The domain this rule applies to.")
    excluded = serializers.BooleanField(
        read_only=True, help_text="Whether to exclude this user from automatic suggestions for the domain."
    )
    revision = serializers.IntegerField(
        read_only=True, help_text="Preference version; older cleanup operations stop after a change."
    )
    updated_at = serializers.DateTimeField(read_only=True, help_text="When this preference last changed.")

    class Meta:
        model = SignalDomainPreference
        fields = ["id", "domain", "excluded", "revision", "updated_at"]


class SignalDomainPreferenceWriteSerializer(serializers.Serializer):
    domain_id = serializers.UUIDField(help_text="Product domain in this project.")
    excluded = serializers.BooleanField(
        help_text="Enable or disable this personal rule. Enabling here affects future routing without a backlog operation."
    )


class SignalDomainPreviewSerializer(serializers.Serializer):
    domain_id = serializers.UUIDField(help_text="Domain whose existing suggestions should be previewed for removal.")


class SignalRoutingBatchSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(
        read_only=True, help_text="Operation ID used to apply, inspect, retry, or undo this preview."
    )
    domain_id = serializers.UUIDField(
        source="preference.domain_id", read_only=True, help_text="The product domain matched by this operation."
    )
    status = serializers.ChoiceField(
        choices=SignalRoutingBatch.Status.choices, read_only=True, help_text="Preview, cleanup, or undo progress."
    )
    total = serializers.IntegerField(
        read_only=True, help_text="Number of report suggestions included in the saved preview."
    )
    changed = serializers.IntegerField(read_only=True, help_text="Suggestions removed by this operation.")
    skipped_claims = serializers.IntegerField(
        read_only=True, help_text="Reports preserved because the user has taken ownership."
    )
    skipped_changes = serializers.IntegerField(
        read_only=True, help_text="Reports skipped because subsequent edits or rules superseded the operation."
    )
    error = serializers.CharField(
        read_only=True, allow_blank=True, help_text="Stable failure category, empty when no failure occurred."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the preview snapshot was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="Most recent operation update.")

    class Meta:
        model = SignalRoutingBatch
        fields = [
            "id",
            "domain_id",
            "status",
            "total",
            "changed",
            "skipped_claims",
            "skipped_changes",
            "error",
            "created_at",
            "updated_at",
        ]


class SignalRoutingBatchReportSerializer(serializers.ModelSerializer):
    report_id = serializers.UUIDField(read_only=True, help_text="Report included in this preview.")
    title = serializers.CharField(source="report.title", read_only=True, help_text="Current report title.")
    status = serializers.ChoiceField(
        choices=SignalRoutingBatchChange.Status.choices,
        read_only=True,
        help_text="Outcome for this report in the operation.",
    )
    has_active_claim = serializers.BooleanField(
        read_only=True, help_text="Whether the preference owner currently owns active work on this report."
    )

    class Meta:
        model = SignalRoutingBatchChange
        fields = ["report_id", "title", "status", "has_active_claim"]


class SignalPersonalCorrectionSerializer(serializers.Serializer):
    excluded = serializers.BooleanField(
        help_text="Whether an explicit per-report Not me correction is active for the current user."
    )
    has_active_claim = serializers.BooleanField(
        help_text="Whether this user still owns active work on the report; removing a suggestion does not release it."
    )


class SignalRoutingProposalWriteSerializer(serializers.Serializer):
    domain_id = serializers.UUIDField(allow_null=True, help_text="Proposed primary domain, or null to abstain.")
    domain_revision = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
        help_text="Revision of the domain definition used by this classifier.",
    )
    report_revision = serializers.DateTimeField(help_text="Report updated_at value on which this proposal is based.")
    method = serializers.ChoiceField(
        choices=SignalRoutingProposal.Method.choices, help_text="Classifier under evaluation."
    )
    version = serializers.CharField(max_length=100, help_text="Model/prompt version identifying this comparison.")
    confidence = serializers.FloatField(
        min_value=0,
        max_value=1,
        allow_null=True,
        required=False,
        help_text="Score for evaluation, never a routing authorization.",
    )
    explanation = serializers.CharField(
        max_length=500, help_text="Why this capability needs fixing, or why classification abstained."
    )
    evidence = serializers.ListField(
        child=serializers.CharField(max_length=500),
        max_length=10,
        required=False,
        help_text="Bounded evidence references, not raw customer content.",
    )


class SignalRoutingProposalSerializer(serializers.ModelSerializer):
    domain = SignalProductDomainSerializer(read_only=True, allow_null=True)

    class Meta:
        model = SignalRoutingProposal
        fields = [
            "id",
            "domain",
            "domain_revision",
            "report_revision",
            "method",
            "version",
            "confidence",
            "explanation",
            "evidence",
            "updated_at",
        ]
        read_only_fields = fields


class SignalRoutingSuggestionSerializer(serializers.Serializer):
    domain = SignalProductDomainSerializer(read_only=True)
    removals = serializers.IntegerField(
        read_only=True, help_text="Distinct self-removals from current reports in the last 30 days."
    )
    explanation = serializers.CharField(
        read_only=True, help_text="Evidence supporting a suggestion, never an automatically saved rule."
    )
