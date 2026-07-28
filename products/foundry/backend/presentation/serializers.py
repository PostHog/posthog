"""DRF serializers for foundry."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.tasks.backend.facade.sandbox import SandboxTemplate

from ..facade.contracts import BetDTO, BetEventDTO, BetNodeDTO
from ..facade.enums import EXTERNAL_EVENT_KINDS, BetEventKind, BetVerdict, ExecutionMode, GateCheckType


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
    label = serializers.CharField(  # type: ignore[assignment]  # field name intentionally shadows Field.label
        help_text="Short label for the lineage source, e.g. 'signal: checkout error spike'."
    )
    url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Link to the originating signal or report.",
    )


class CommandCheckParamsSerializer(serializers.Serializer):
    command = serializers.CharField(help_text="Shell command to run in the gate sandbox. Exit code 0 passes.")


class CoverageCheckParamsSerializer(serializers.Serializer):
    command = serializers.CharField(
        help_text="Shell command to run in the gate sandbox that produces a coverage report at report_path."
    )
    report_format = serializers.ChoiceField(
        choices=["lcov", "cobertura"],
        help_text=(
            "Coverage report format: 'lcov' (lcov.info-style) or 'cobertura' (coverage.py's "
            "`coverage xml` output, which is Cobertura-compatible XML)."
        ),
    )
    report_path = serializers.CharField(
        help_text="Path, relative to the artifact repo root, the command writes its coverage report to."
    )
    min_changed_line_pct = serializers.FloatField(
        min_value=0,
        max_value=100,
        help_text="Minimum percentage of the artifact diff's added/changed lines that must be covered to pass.",
    )


class MutationCheckParamsSerializer(serializers.Serializer):
    command = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Optional command template for mutation testing; '{files}' is replaced with the "
            "shell-quoted list of changed files. Leave blank to use the built-in mutmut "
            "invocation restricted to those files."
        ),
    )
    min_score_pct = serializers.FloatField(
        min_value=0, max_value=100, help_text="Minimum percentage of generated mutants that must be killed to pass."
    )
    max_minutes = serializers.IntegerField(
        min_value=1,
        help_text="Hard time box for the mutation run; exceeding it fails the check rather than hanging.",
    )


class FlagGuardCheckParamsSerializer(serializers.Serializer):
    flag_key = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Feature flag key every changed executable region should reference. Defaults to 'bet-<slug>'.",
    )
    exempt_paths = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Path prefixes (e.g. 'tests/', 'docs/') exempt from the flag-guard heuristic.",
    )


class ReviewhogCheckParamsSerializer(serializers.Serializer):
    """No params yet — the check runs off the artifact's pr_url. An explicit (empty)
    serializer gives future params a validated home and still rejects unknown ones."""


_CHECK_PARAMS_SERIALIZERS: dict[GateCheckType, type[serializers.Serializer]] = {
    GateCheckType.COMMAND: CommandCheckParamsSerializer,
    GateCheckType.COVERAGE: CoverageCheckParamsSerializer,
    GateCheckType.MUTATION: MutationCheckParamsSerializer,
    GateCheckType.FLAG_GUARD: FlagGuardCheckParamsSerializer,
    GateCheckType.REVIEWHOG: ReviewhogCheckParamsSerializer,
}


class GateCheckSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Short identifier for this check, shown in the gate card breakdown.")
    check_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in GateCheckType],
        help_text="One of 'command', 'coverage', 'mutation', 'flag_guard', 'reviewhog'.",
    )
    required = serializers.BooleanField(  # type: ignore[assignment]  # field name intentionally shadows Field.required
        required=False,
        default=True,
        help_text=(
            "Required checks must pass for the gate to pass; a failing optional check is "
            "recorded in the breakdown but doesn't block gating."
        ),
    )
    params = JSONObjectField(
        required=False,
        default=dict,
        help_text="Type-specific parameters; shape depends on check_type (see the per-type params serializers).",
    )

    def validate(self, attrs: dict) -> dict:
        params_serializer_cls = _CHECK_PARAMS_SERIALIZERS[GateCheckType(attrs["check_type"])]
        params_serializer = params_serializer_cls(data=attrs.get("params") or {})
        if not params_serializer.is_valid():
            raise serializers.ValidationError({"params": params_serializer.errors})
        attrs["params"] = params_serializer.validated_data
        return attrs


class GateArtifactConfigSerializer(serializers.Serializer):
    template = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SandboxTemplate],
        required=False,
        default=SandboxTemplate.SLIM_BASE.value,
        help_text="Sandbox template the gauntlet checks out the artifact and runs its checks in.",
    )


class GateConfigSerializer(serializers.Serializer):
    checks = serializers.ListField(
        child=GateCheckSerializer(),
        required=False,
        default=list,
        help_text="The constraint battery run against the artifact diff. Empty means no automatic gauntlet run.",
    )
    protected_paths = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text=(
            "Path prefixes the builder may never touch (e.g. the test-writer's acceptance tests). "
            "Non-empty implicitly adds an always-on, always-required 'protected_paths' check to "
            "the gate.result breakdown."
        ),
    )
    artifact = GateArtifactConfigSerializer(
        required=False, default=dict, help_text="Sandbox config the gauntlet provisions to run checks in."
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
    execution_mode = serializers.ChoiceField(
        choices=[(m.value, m.value) for m in ExecutionMode],
        help_text="'external': any orchestrator POSTs events. 'managed': Foundry drives the run via Temporal.",
    )
    run_config = JSONObjectField(
        help_text="Managed-mode execution config: {image/template, command, env allowlist, caps}."
    )
    memory_repo_url = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Git-backed memory repo cloned into managed nodes' sandboxes at a conventional path.",
    )
    gate_config = GateConfigSerializer(
        help_text="The gauntlet's constraint battery: checks, protected_paths, and artifact sandbox config."
    )

    class Meta:
        dataclass = BetDTO


class BetEventSerializer(DataclassSerializer):
    payload = JSONObjectField(help_text="Event payload as reported by the orchestrator.")

    class Meta:
        dataclass = BetEventDTO


class BetNodeSerializer(DataclassSerializer):
    class Meta:
        dataclass = BetNodeDTO


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
    execution_mode = serializers.ChoiceField(
        choices=[(m.value, m.value) for m in ExecutionMode],
        required=False,
        default=ExecutionMode.EXTERNAL,
        help_text="'external': any orchestrator POSTs events. 'managed': Foundry drives the run via Temporal.",
    )
    run_config = JSONObjectField(
        required=False,
        default=dict,
        help_text="Managed-mode execution config: {image/template, command, env allowlist, caps}.",
    )
    memory_repo_url = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Git-backed memory repo cloned into managed nodes' sandboxes at a conventional path.",
    )
    gate_config = GateConfigSerializer(
        required=False,
        default=dict,
        help_text="The gauntlet's constraint battery: checks, protected_paths, and artifact sandbox config.",
    )


class NodeSpawnedPayloadSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="Orchestrator-supplied identifier, unique per bet.")
    parent_node_id = serializers.CharField(
        required=False, allow_null=True, default=None, help_text="node_id of the spawning node; null for the root."
    )
    runner = serializers.CharField(required=False, allow_blank=True, default="", help_text="e.g. 'claude-code'.")
    depth = serializers.IntegerField(required=False, default=0, help_text="Distance from the root node.")
    max_cost = serializers.FloatField(required=False, allow_null=True, default=None, help_text="Cost cap, if any.")
    max_depth = serializers.IntegerField(required=False, allow_null=True, default=None, help_text="Depth cap, if any.")
    max_children = serializers.IntegerField(
        required=False, allow_null=True, default=None, help_text="Direct-children cap, if any."
    )
    command = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="The command this node runs, for display."
    )
    sandbox_external_id = serializers.CharField(
        required=False, allow_null=True, default=None, help_text="Sandbox provider id backing this node."
    )


class NodeFinishedPayloadSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="node_id of the node that finished.")
    cost = serializers.FloatField(required=False, allow_null=True, default=None, help_text="Cost this node incurred.")
    summary = serializers.CharField(required=False, allow_blank=True, default="", help_text="Short outcome summary.")


class NodeFailedPayloadSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="node_id of the node that failed.")
    cost = serializers.FloatField(required=False, allow_null=True, default=None, help_text="Cost this node incurred.")
    summary = serializers.CharField(required=False, allow_blank=True, default="", help_text="Failure summary.")


class BudgetExceededPayloadSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="node_id whose subtree was cancelled.")
    cap = serializers.ChoiceField(
        choices=["max_depth", "max_children", "cost"],
        help_text="Which cap tripped.",
    )
    detail = serializers.CharField(required=False, allow_blank=True, default="", help_text="Human-readable detail.")


class KnowledgePublishedPayloadSerializer(serializers.Serializer):
    repo = serializers.CharField(help_text="Memory repo URL the entry was published to.")
    ref = serializers.CharField(required=False, allow_blank=True, default="", help_text="Commit/ref of the entry.")
    path = serializers.CharField(required=False, allow_blank=True, default="", help_text="Path within the repo.")
    title = serializers.CharField(required=False, allow_blank=True, default="", help_text="Short entry title.")


class ArtifactReadyPayloadSerializer(serializers.Serializer):
    """Standardized artifact contract the gauntlet checks out and diffs. All fields stay
    optional so pre-ADR-4 free-form payloads (e.g. bare pr_url) keep validating."""

    repo_url = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Git URL of the artifact's repo."
    )
    ref = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Commit/ref the gauntlet checks out and diffs."
    )
    base_ref = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Base commit/ref the diff is computed against."
    )
    pr_url = serializers.CharField(
        required=False, allow_null=True, default=None, help_text="Optional PR URL, used by the reviewhog check."
    )


_TYPED_PAYLOAD_SERIALIZERS: dict[BetEventKind, type[serializers.Serializer]] = {
    BetEventKind.NODE_SPAWNED: NodeSpawnedPayloadSerializer,
    BetEventKind.NODE_FINISHED: NodeFinishedPayloadSerializer,
    BetEventKind.NODE_FAILED: NodeFailedPayloadSerializer,
    BetEventKind.BUDGET_EXCEEDED: BudgetExceededPayloadSerializer,
    BetEventKind.KNOWLEDGE_PUBLISHED: KnowledgePublishedPayloadSerializer,
    BetEventKind.ARTIFACT_READY: ArtifactReadyPayloadSerializer,
}


class CreateBetEventSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=[(k.value, k.value) for k in EXTERNAL_EVENT_KINDS],
        help_text="Typed event kind reported by the orchestrator. 'gate.result' with payload {pass: true} advances building → gated.",
    )
    payload = JSONObjectField(
        required=False,
        default=dict,
        help_text="Event payload. For 'gate.result': {pass: bool, violations: [{code, message, severity}]}. "
        "Node/knowledge/artifact kinds (node.spawned, node.finished, node.failed, budget.exceeded, "
        "knowledge.published, artifact.ready) are validated against a typed shape.",
    )

    def validate(self, attrs: dict) -> dict:
        payload_serializer_cls = _TYPED_PAYLOAD_SERIALIZERS.get(BetEventKind(attrs["kind"]))
        if payload_serializer_cls is not None:
            payload_serializer = payload_serializer_cls(data=attrs.get("payload") or {})
            if not payload_serializer.is_valid():
                raise serializers.ValidationError({"payload": payload_serializer.errors})
            attrs["payload"] = payload_serializer.validated_data
        return attrs


class RecordVerdictSerializer(serializers.Serializer):
    verdict = serializers.ChoiceField(
        choices=[(v.value, v.value) for v in BetVerdict],
        help_text="'promoted' or 'rolled_back' archives the bet; 'iterate' sends it back to building with an incremented iteration counter.",
    )
