from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.notebooks.backend.models import NotebookGenUI


class GenUIEnsureRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=20_000,
        trim_whitespace=False,
        help_text="Instructions for the custom visualization.",
    )
    inputs = serializers.ListField(
        child=serializers.CharField(max_length=128),
        max_length=4,
        help_text="Ordered dataframe names the visualization may read.",
    )
    legacy_canvas_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Existing POC canvas to adopt when this notebook node has no persisted GenUI state.",
    )


class GenUIInputColumnSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Dataframe column name.")
    type = serializers.CharField(help_text="Dataframe column type reported by the notebook run.")


class GenUIInputStateSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Requested dataframe name.")
    input_status = serializers.ChoiceField(
        choices=["missing", "never_run", "running", "failed", "interrupted", "stale", "ready"],
        help_text="Current lifecycle state of the cell that produces this dataframe.",
    )
    producer_node_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Notebook node that produces the dataframe, when one exists.",
    )
    run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Latest upstream notebook run used for freshness checks.",
    )
    columns = GenUIInputColumnSerializer(
        many=True,
        required=False,
        help_text="Columns in the saved dataframe preview.",
    )
    totalRowCount = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Total rows reported by the upstream run.",
    )
    includedRowCount = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="Rows copied into the bounded GenUI snapshot.",
    )
    truncated = serializers.BooleanField(
        required=False,
        help_text="Whether the snapshot contains fewer rows than the upstream result.",
    )
    error = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Bounded upstream error when the dataframe is unavailable.",
    )


class GenUIStatusSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="Stable notebook node identifier.")
    lifecycle_status = serializers.ChoiceField(
        choices=NotebookGenUI.LifecycleStatus.choices,
        help_text="Current snapshot, generation, build, stale, or failure lifecycle state.",
    )
    staleness_reason = serializers.ChoiceField(
        choices=["upstream_runs_changed", "prompt_or_schema_changed"],
        required=False,
        allow_null=True,
        help_text="Why a ready visualization needs a run or regeneration.",
    )
    error_code = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Stable machine-readable failure code.",
    )
    error_detail = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Bounded failure detail with a next action.",
    )
    artifact_url = serializers.URLField(
        required=False,
        allow_null=True,
        help_text="Short-lived URL for the last successful visualization artifact.",
    )
    frame_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Dataframes the artifact may request through ph.readFrame.",
    )
    source_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Last successfully published Canvas source version.",
    )
    build_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Last successfully published Canvas build.",
    )
    input_states = GenUIInputStateSerializer(
        many=True,
        help_text="Current state and schema of every requested dataframe.",
    )
    can_run = serializers.BooleanField(help_text="Whether Run can refresh snapshots without model generation.")
    can_regenerate = serializers.BooleanField(help_text="Whether the visualization can be explicitly regenerated.")
    can_retry = serializers.BooleanField(help_text="Whether the last terminal generation failure can be retried.")
    created_at = serializers.DateTimeField(help_text="When persisted state for this notebook node was created.")
    updated_at = serializers.DateTimeField(help_text="When the lifecycle state last changed.")
    generated_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the current generated source became live.",
    )
    snapshot_updated_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the active dataframe snapshot last changed.",
    )


class GenUIErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable machine-readable error code.")
    detail = serializers.CharField(help_text="Error detail with a next action.")


class GenUISourceSerializer(serializers.Serializer):
    version_id = serializers.UUIDField(help_text="Source version shown in the response.")
    source = serializers.CharField(  # type: ignore[assignment]  # API field name shadows DRF's typed Field.source attribute
        help_text="Generated React component source.",
    )


class GenUIVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Immutable source version identifier.")
    prompt = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Description recorded when the source version was generated.",
    )
    created_at = serializers.DateTimeField(help_text="When the source version was generated.")
    is_current = serializers.BooleanField(help_text="Whether this version backs the live notebook visualization.")


class GenUIRestoreVersionRequestSerializer(serializers.Serializer):
    version_id = serializers.UUIDField(help_text="Existing source version to make current.")


@extend_schema_field(OpenApiTypes.ANY)
class GenUIFrameCellField(serializers.Field):
    def to_representation(self, value: object) -> object:
        return value


class GenUIFrameSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Dataframe name.")
    columns = GenUIInputColumnSerializer(many=True, help_text="Dataframe columns and types.")
    rows = serializers.ListField(
        child=serializers.ListField(child=GenUIFrameCellField()),
        help_text="Bounded, JSON-safe preview rows.",
    )
    totalRowCount = serializers.IntegerField(min_value=0, help_text="Total rows reported by the upstream run.")
    includedRowCount = serializers.IntegerField(min_value=0, help_text="Rows included in this snapshot.")
    truncated = serializers.BooleanField(help_text="Whether rows were omitted from the bounded snapshot.")
