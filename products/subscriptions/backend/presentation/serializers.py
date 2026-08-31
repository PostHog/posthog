from collections.abc import Mapping
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.subscriptions.backend.facade.contracts import (
    ArtifactLinkDTO,
    OutcomeDecisionDTO,
    OutcomeReadoutHistoryDTO,
    PulseExperimentDraftInput,
    PulseExperimentMetricRef,
    PulseExperimentVariant,
    PulseRunHistoryDTO,
    RunActionHistoryDTO,
)


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data: Mapping[str, Any]) -> dict[str, Any]:
        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError({field: ["This field is not allowed."] for field in unknown_fields})
        return super().to_internal_value(data)


class ProactiveSubscriptionConfigWriteSerializer(StrictSerializer):
    enabled = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether future AI report deliveries may run proactive follow-up.",
    )
    repository = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=255,
        help_text="Exact repository in owner/repository format. Required before draft pull requests are allowed.",
    )
    repository_integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="Exact GitHub integration selected with the repository for draft pull request authorization.",
    )
    create_draft_pr = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether Pulse may create one draft pull request on a future delivery.",
    )
    public_research_subject_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional eligible reviewed public research subject. Omit to disable public research.",
    )


class ProactiveSubscriptionConfigSerializer(ProactiveSubscriptionConfigWriteSerializer):
    repository_grant_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Server-issued active repository grant for the selected repository. It cannot be chosen by clients.",
    )


class PulseHistoryQuerySerializer(serializers.Serializer):
    subscription_id = serializers.IntegerField(
        min_value=1,
        help_text="Subscription whose bounded proactive delivery history to return.",
    )


class OutcomeDecisionSerializer(StrictSerializer):
    decision = serializers.ChoiceField(
        choices=("adopted", "dismissed"),
        help_text="Whether to adopt or dismiss this advice-only recommendation.",
    )


class OutcomeDecisionResponseSerializer(DataclassSerializer):
    class Meta:
        dataclass = OutcomeDecisionDTO
        extra_kwargs = {
            "plan_id": {"help_text": "Stable outcome plan that records this advice decision."},
            "action_id": {"help_text": "Stable advice-only recommendation receiving this decision."},
            "adoption_status": {"help_text": "Current explicit decision: adopted or dismissed."},
            "readout_status": {"help_text": "Current server-owned measurement lifecycle state."},
            "adopted_at": {"help_text": "When the recommendation was most recently adopted, if adopted."},
            "decision_at": {"help_text": "When the current explicit decision was recorded."},
            "decided_by_id": {"help_text": "Server-known identifier of the person who made the decision."},
            "next_readout_at": {"help_text": "Scheduled readout time after adoption, if any."},
        }


class ArtifactLinkHistorySerializer(DataclassSerializer):
    class Meta:
        dataclass = ArtifactLinkDTO
        extra_kwargs = {
            "kind": {"help_text": "Server-owned prepared artifact kind."},
            "status": {"help_text": "Current server-owned artifact state."},
            "external_url": {"help_text": "Authoritative verified artifact URL, when safe to expose."},
            "external_state": {"help_text": "Verified external lifecycle state, when available."},
            "failure_code": {"help_text": "Bounded server-owned artifact failure code, if any."},
            "task_id": {"help_text": "Server task that prepared this artifact, if any."},
            "execution_task_run_id": {"help_text": "Execution task-run identifier for this artifact, if any."},
            "experiment_id": {"help_text": "Verified experiment identifier for an experiment artifact, if any."},
        }


class RunActionHistorySerializer(DataclassSerializer):
    artifacts = ArtifactLinkHistorySerializer(many=True, help_text="Safe prepared artifacts for this recommendation.")

    class Meta:
        dataclass = RunActionHistoryDTO
        extra_kwargs = {
            "id": {"help_text": "Stable recommendation identifier."},
            "action_key": {"help_text": "Stable server-generated recommendation key."},
            "kind": {"help_text": "Recommendation or prepared-action kind."},
            "title": {"help_text": "Safe recommendation title."},
            "rationale": {"help_text": "Safe recommendation rationale."},
            "expected_impact": {"help_text": "Safe expected impact summary."},
            "rank": {"help_text": "Server-ranked recommendation position."},
            "implementation_selected": {"help_text": "Whether the server selected this action for implementation."},
            "status": {"help_text": "Current server-owned action state."},
            "why_now": {"help_text": "Safe reason this recommendation is timely."},
            "confidence": {"help_text": "Bounded recommendation confidence, if available."},
            "effort": {"help_text": "Estimated implementation effort."},
            "metric_name": {"help_text": "Safe metric name used for the recommendation."},
            "metric_unit": {"help_text": "Metric unit."},
            "metric_direction": {"help_text": "Intended metric direction."},
            "expected_change_type": {"help_text": "Expected-change interpretation."},
            "expected_change_lower": {"help_text": "Lower expected change bound."},
            "expected_change_upper": {"help_text": "Upper expected change bound."},
            "readout_after_days": {"help_text": "Readout delay in days, if measurable."},
            "plan_id": {"help_text": "Linked server-owned outcome plan, if any."},
            "baseline_value": {"help_text": "Outcome-plan baseline value, if any."},
            "baseline_from": {"help_text": "Start of the baseline interval, if any."},
            "baseline_to": {"help_text": "End of the baseline interval, if any."},
            "adoption_status": {"help_text": "Current outcome adoption state, if measurable."},
            "adoption_source": {"help_text": "Bounded source of the current adoption state, if any."},
            "adopted_at": {"help_text": "Most recent adoption timestamp, if adopted."},
            "decision_at": {"help_text": "Timestamp of the current manual decision, if any."},
            "decided_by_id": {"help_text": "Person who made the current manual decision, if any."},
            "readout_status": {"help_text": "Current outcome readout lifecycle state, if measurable."},
            "next_readout_at": {"help_text": "Next scheduled outcome readout, if any."},
            "evidence": {"help_text": "Safe bounded evidence provenance."},
            "citations": {"help_text": "Safe bounded public research citations."},
            "build_test_gate": {"help_text": "Verified build and test gate result, if relevant."},
        }


class OutcomeReadoutHistorySerializer(DataclassSerializer):
    artifacts = ArtifactLinkHistorySerializer(
        many=True,
        help_text="Safe artifacts prepared for the source recommendation.",
    )

    class Meta:
        dataclass = OutcomeReadoutHistoryDTO
        extra_kwargs = {
            "id": {"help_text": "Stable immutable outcome observation identifier."},
            "plan_id": {"help_text": "Outcome plan measured by this readout."},
            "action_id": {"help_text": "Source recommendation for this readout."},
            "recommendation_title": {"help_text": "Safe source recommendation title."},
            "metric_name": {"help_text": "Adapter-owned identity for the count scalar."},
            "metric_unit": {"help_text": "Adapter-owned count scalar unit."},
            "baseline_value": {"help_text": "Server-owned baseline metric value."},
            "baseline_from": {"help_text": "Start of the baseline interval."},
            "baseline_to": {"help_text": "End of the baseline interval."},
            "observed_value": {"help_text": "Observed metric value, if measurement succeeded."},
            "observed_from": {"help_text": "Start of the observed interval, if available."},
            "observed_to": {"help_text": "End of the observed interval, if available."},
            "absolute_delta": {"help_text": "Observed absolute change, if available."},
            "relative_delta": {"help_text": "Observed relative change, if available."},
            "status": {"help_text": "Immutable observation state."},
            "verdict": {"help_text": "Server-owned outcome verdict."},
            "confidence": {"help_text": "Server-derived readout confidence, if available."},
            "failure_code": {"help_text": "Bounded measurement failure code, if any."},
        }


class PulseRunHistorySerializer(DataclassSerializer):
    actions = RunActionHistorySerializer(many=True, help_text="Bounded safe recommendation history.")
    readouts = OutcomeReadoutHistorySerializer(
        many=True,
        help_text="Immutable authorized outcome readouts, shown before recommendations.",
    )

    class Meta:
        dataclass = PulseRunHistoryDTO
        extra_kwargs = {
            "id": {"help_text": "Stable proactive run identifier."},
            "subscription_id": {"help_text": "Subscription that owns this run."},
            "delivery_id": {"help_text": "Delivery that triggered this run."},
            "status": {"help_text": "Terminal or current Pulse run state."},
            "started_at": {"help_text": "When the run began, if started."},
            "finished_at": {"help_text": "When the run finished, if terminal."},
            "task_id": {"help_text": "Analysis task identifier, if any."},
            "analysis_task_run_id": {"help_text": "Analysis task-run identifier, if any."},
            "execution_task_run_id": {"help_text": "Execution task-run identifier, if any."},
            "failure_code": {"help_text": "Bounded run failure code, if any."},
            "skip_reason": {"help_text": "Bounded reason a run was skipped, if any."},
            "deliveries": {"help_text": "Bounded delivery outcomes for this run."},
        }


class RepositoryOptionSerializer(serializers.Serializer):
    repository = serializers.CharField(
        help_text="Exact repository currently authorizable by the requesting user, in owner/repository format."
    )
    repository_integration_id = serializers.IntegerField(
        min_value=1,
        help_text="Exact active GitHub integration that authorizes this repository binding.",
    )


class PublicResearchSubjectOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable identifier of the reviewed public research subject.")
    display_name = serializers.CharField(help_text="Human-readable name of the reviewed public research subject.")
    canonical_domain = serializers.CharField(help_text="Canonical public domain covered by this research subject.")


@extend_schema_serializer(many=False)
class ProactiveConfigurationOptionsSerializer(serializers.Serializer):
    proactive_available = serializers.BooleanField(
        help_text="Whether proactive subscription configuration is enabled for this server."
    )
    draft_pr_available = serializers.BooleanField(
        help_text="Whether the server currently allows new draft pull request automation."
    )
    repositories = serializers.ListField(
        child=RepositoryOptionSerializer(),
        help_text="Repositories that the requesting user can currently authorize for a draft pull request.",
    )
    public_research_subjects = serializers.ListField(
        child=PublicResearchSubjectOptionSerializer(),
        help_text="Eligible reviewed public research subjects while public research is enabled.",
    )


class PulseExperimentVariantSerializer(StrictSerializer):
    key = serializers.RegexField(
        regex=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$",
        max_length=100,
        help_text="New variant key. It cannot identify an existing feature flag.",
    )
    name = serializers.CharField(max_length=400, trim_whitespace=True, help_text="Display name for this variant.")


class PulseExperimentMetricRefSerializer(StrictSerializer):
    kind = serializers.ChoiceField(
        choices=("event", "action"),
        help_text="Metric reference type. Pulse accepts only an event name or an action ID.",
    )
    event_name = serializers.CharField(
        required=False,
        max_length=400,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Existing event name when kind is event.",
    )
    action_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Existing project action ID when kind is action.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["kind"] == "event" and ("event_name" not in attrs or "action_id" in attrs):
            raise serializers.ValidationError("Event metrics require event_name only.")
        if attrs["kind"] == "action" and ("action_id" not in attrs or "event_name" in attrs):
            raise serializers.ValidationError("Action metrics require action_id only.")
        return attrs


class PulseExperimentDraftSerializer(StrictSerializer):
    name = serializers.CharField(
        max_length=400,
        trim_whitespace=True,
        help_text="Name for the new inert experiment draft.",
    )
    hypothesis = serializers.CharField(
        max_length=1200,
        trim_whitespace=True,
        help_text="Testable hypothesis recorded on the draft.",
    )
    description = serializers.CharField(
        required=False,
        default="",
        max_length=1200,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Optional explanation of the proposed change.",
    )
    target_description = serializers.CharField(
        max_length=600,
        trim_whitespace=True,
        help_text="Plain-language audience or behavior targeted by the draft.",
    )
    variants = serializers.ListField(
        child=PulseExperimentVariantSerializer(),
        min_length=2,
        max_length=5,
        help_text="Two to five new variants. Rollout percentages are derived server-side.",
    )
    primary_metric = PulseExperimentMetricRefSerializer(
        help_text="One existing event or action used as the primary metric."
    )
    secondary_metrics = serializers.ListField(
        child=PulseExperimentMetricRefSerializer(),
        required=False,
        default=list,
        max_length=9,
        help_text="Up to nine existing event or action references used as secondary metrics.",
    )

    def validate_variants(self, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys = [variant["key"] for variant in variants]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("Variant keys must be unique.")
        return variants

    @staticmethod
    def to_dto(data: dict[str, Any]) -> PulseExperimentDraftInput:
        primary_metric = data["primary_metric"]
        return PulseExperimentDraftInput(
            name=data["name"],
            hypothesis=data["hypothesis"],
            description=data["description"],
            target_description=data["target_description"],
            variants=tuple(PulseExperimentVariant(**variant) for variant in data["variants"]),
            primary_metric=PulseExperimentMetricRef(**primary_metric),
            secondary_metrics=tuple(PulseExperimentMetricRef(**metric) for metric in data["secondary_metrics"]),
        )


class PulseExperimentDraftResponseSerializer(serializers.Serializer):
    artifact_id = serializers.UUIDField(help_text="Reserved Pulse artifact that owns this draft.")
    action_id = serializers.UUIDField(help_text="Selected Pulse action fulfilled by this draft.")
    experiment_id = serializers.IntegerField(min_value=1, help_text="Created inert experiment draft.")
    feature_flag_id = serializers.IntegerField(min_value=1, help_text="Created inactive zero-traffic feature flag.")
    status = serializers.ChoiceField(choices=("verified",), help_text="Whether the draft was verified and recorded.")


@extend_schema_field(OpenApiTypes.OBJECT)
class PulseOutcomeReplayArgumentsField(serializers.JSONField):
    """Adapter-owned input for the returned measurement tool."""


class PulseOutcomeReplayResponseSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField(help_text="Claimed outcome plan this replay instruction is bound to.")
    tool_name = serializers.CharField(
        max_length=100,
        help_text="Only supported read-only measurement tool the current sandbox may execute.",
    )
    tool_schema_version = serializers.CharField(
        max_length=32,
        help_text="Schema version that must match the returned measurement tool call.",
    )
    comparison_arguments = PulseOutcomeReplayArgumentsField(
        help_text="Server-derived measurement arguments. Only the adapter-owned time window differs from baseline.",
    )
    selector = serializers.DictField(
        child=serializers.CharField(),
        help_text="Server-validated value selector for the returned measurement result.",
    )
