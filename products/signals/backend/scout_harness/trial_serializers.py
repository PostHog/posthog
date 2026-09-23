from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.signals.backend.scout_harness.limits import MAX_RUN_NOTE_CHARS
from products.signals.backend.scout_harness.serializers import ScratchpadEntrySerializer
from products.signals.backend.scout_harness.trial_state import TrialReport


class ScoutTrialLaunchSerializer(serializers.Serializer):
    launch_id = serializers.UUIDField(help_text="Unique launch ID. Reuse it only when retrying this exact request.")
    context_id = serializers.UUIDField(
        required=False, help_text="Saved starting context from a previous launch in this comparison."
    )
    variant = serializers.CharField(
        required=False, allow_blank=True, max_length=100, help_text="Operator label for this variant."
    )
    skill_body = serializers.CharField(
        required=False,
        max_length=100_000,
        trim_whitespace=False,
        help_text="Replacement skill body for this run. Supporting files and tool permissions stay pinned.",
    )
    model = serializers.CharField(required=False, max_length=200, help_text="Model identifier for this run.")
    reasoning_effort = serializers.CharField(
        required=False,
        max_length=20,
        help_text="Reasoning effort supported by the selected model. Required when the saved source has no pinned effort.",
    )
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=MAX_RUN_NOTE_CHARS,
        help_text="Common investigation note, saved before applying any variant overrides.",
    )


class ScoutTrialStartedSerializer(serializers.Serializer):
    launch_id = serializers.UUIDField(help_text="Retry-stable launch identity.")
    context_id = serializers.UUIDField(help_text="Starting context to reuse across variants and repetitions.")
    workflow_id = serializers.CharField(help_text="Workflow dispatch identity.")
    model = serializers.CharField(help_text="Resolved model identifier.")
    reasoning_effort = serializers.CharField(help_text="Resolved reasoning effort.")
    variant = serializers.CharField(help_text="Operator label for this variant.")


class ScoutTrialResultQuerySerializer(serializers.Serializer):
    launch_id = serializers.UUIDField(help_text="Launch identity returned by the trial action.")


@extend_schema_field(TrialReport)  # type: ignore[arg-type]
class ScoutTrialReportField(serializers.JSONField):
    pass


class ScoutTrialResultSerializer(serializers.Serializer):
    launch_id = serializers.UUIDField(help_text="Launch identity.")
    context_id = serializers.UUIDField(help_text="Saved starting context identity.")
    model = serializers.CharField(help_text="Resolved model identifier.")
    reasoning_effort = serializers.CharField(help_text="Resolved reasoning effort.")
    skill_body_sha256 = serializers.CharField(help_text="Hash of the skill body delivered to this run.")
    result_key = serializers.CharField(
        allow_null=True, help_text="Private object-storage result reference, when exported."
    )
    export_error = serializers.CharField(
        allow_null=True, help_text="Whether the durable export needs a retry; inline results remain available."
    )
    started_at = serializers.DateTimeField(allow_null=True, help_text="Execution start time.")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="Execution completion time.")
    run_id = serializers.UUIDField(allow_null=True, help_text="Scout run identity once the sandbox is prepared.")
    task_id = serializers.UUIDField(allow_null=True, help_text="Task identity for existing log and cancellation tools.")
    task_run_id = serializers.UUIDField(allow_null=True, help_text="Task execution identity for logs and usage.")
    status = serializers.CharField(help_text="Execution status, or pending while the workflow prepares the run.")
    task_status = serializers.CharField(
        allow_null=True, help_text="Underlying task status; cancel an active task if its workflow failed."
    )
    error = serializers.CharField(
        allow_null=True, help_text="Setup or workflow failure, including failures before a task was created."
    )
    summary = serializers.CharField(allow_blank=True, help_text="Scout close-out summary.")
    invalid_reason = serializers.CharField(
        allow_null=True, help_text="Why this execution cannot be used for comparison."
    )
    reports = serializers.ListField(
        child=ScoutTrialReportField(), help_text="Privately captured report creations and edits."
    )
    memory = serializers.DictField(
        child=ScratchpadEntrySerializer(allow_null=True),
        help_text="Private memory replacements and deleted keys for this run.",
    )
    cost_usd = serializers.FloatField(
        allow_null=True, help_text="Attributed model cost when available; null means unknown."
    )
    input_tokens = serializers.IntegerField(allow_null=True, help_text="Input tokens reported by the agent runtime.")
    output_tokens = serializers.IntegerField(allow_null=True, help_text="Output tokens reported by the agent runtime.")
