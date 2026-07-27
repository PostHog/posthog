"""DRF serializers for foundry."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import BetDTO, BetEventDTO
from ..facade.enums import EXTERNAL_EVENT_KINDS, BetVerdict


@extend_schema_field(OpenApiTypes.OBJECT)
class JSONObjectField(serializers.JSONField):
    pass


class SuccessMetricSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Human-readable name of the metric the bet is judged on.")
    target = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Target for the metric, e.g. '+10%' or '>= 0.42'. Free-form; the experiment carries the formal definition.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional longer description of how the metric is measured.",
    )


class GuardrailSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Name of the guardrail metric that must not regress.")
    constraint = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Constraint the guardrail enforces, e.g. 'error rate must not rise'.",
    )


class BudgetSerializer(serializers.Serializer):
    usd = serializers.FloatField(required=False, help_text="Maximum spend for the bet's execution, in USD.")
    time_hours = serializers.IntegerField(required=False, help_text="Wall-clock budget for the bet, in hours.")
    iterations = serializers.IntegerField(
        required=False, help_text="Maximum number of build iterations before the bet expires."
    )


class SourceRefSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Short label for the lineage source, e.g. 'signal: checkout error spike'.")
    url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Link to the originating signal or report.",
    )


class BetSerializer(DataclassSerializer):
    success_metric = SuccessMetricSerializer(help_text="The single metric that decides whether the bet wins.")
    guardrails = serializers.ListField(
        child=GuardrailSerializer(),
        help_text="Metrics that must not regress while the bet is exposed.",
    )
    budget = BudgetSerializer(help_text="Resource ceiling for autonomous execution.")
    exposure_plan = JSONObjectField(
        help_text="How the bet should be rolled out once gated (free-form, consumed by the orchestrator)."
    )
    sources = serializers.ListField(
        child=SourceRefSerializer(),
        help_text="Lineage references to the signals/reports that motivated the bet.",
    )

    class Meta:
        dataclass = BetDTO


class BetEventSerializer(DataclassSerializer):
    payload = JSONObjectField(help_text="Event payload as reported by the orchestrator.")

    class Meta:
        dataclass = BetEventDTO


class CreateBetSerializer(serializers.Serializer):
    slug = serializers.SlugField(
        max_length=200,
        help_text="Unique-per-project identifier; also seeds the feature flag key ('bet-<slug>').",
    )
    hypothesis = serializers.CharField(help_text="The falsifiable statement this bet exists to test.")
    success_metric = SuccessMetricSerializer(help_text="The single metric that decides whether the bet wins.")
    guardrails = serializers.ListField(
        child=GuardrailSerializer(),
        required=False,
        default=list,
        help_text="Metrics that must not regress while the bet is exposed.",
    )
    budget = BudgetSerializer(required=False, default=dict, help_text="Resource ceiling for autonomous execution.")
    exposure_plan = JSONObjectField(
        required=False,
        default=dict,
        help_text="How the bet should be rolled out once gated (free-form, consumed by the orchestrator).",
    )
    sources = serializers.ListField(
        child=SourceRefSerializer(),
        required=False,
        default=list,
        help_text="Lineage references to the signals/reports that motivated the bet.",
    )
    ttl = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default=None,
        help_text="When the bet expires if unresolved.",
    )


class CreateBetEventSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=[(k.value, k.value) for k in EXTERNAL_EVENT_KINDS],
        help_text="Typed event kind reported by the orchestrator. 'gate.result' with payload {pass: true} advances building → gated.",
    )
    payload = JSONObjectField(
        required=False,
        default=dict,
        help_text="Event payload. For 'gate.result': {pass: bool, violations: [{code, message, severity}]}.",
    )


class RecordVerdictSerializer(serializers.Serializer):
    verdict = serializers.ChoiceField(
        choices=[(v.value, v.value) for v in BetVerdict],
        help_text="'promoted' or 'rolled_back' archives the bet; 'iterate' sends it back to building with an incremented iteration counter.",
    )
