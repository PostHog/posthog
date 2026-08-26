from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.notebooks.backend.genui_models import DEFAULT_GENUI_MODEL, GENUI_MODEL_CHOICES


class GenUIGenerateRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=20_000,
        trim_whitespace=False,
        help_text="Instructions for the generated visualization.",
    )
    generation_id = serializers.UUIDField(help_text="Unique identifier used to cancel this generation request.")
    model = serializers.ChoiceField(
        choices=GENUI_MODEL_CHOICES,
        default=DEFAULT_GENUI_MODEL,
        help_text="AI model used to generate the visualization.",
    )
    operation = serializers.ChoiceField(
        choices=["initial", "regenerate", "improve"],
        default="regenerate",
        help_text="Whether to generate from scratch or improve the current source.",
    )


class GenUICancelRequestSerializer(serializers.Serializer):
    generation_id = serializers.UUIDField(help_text="Identifier of the generation request to cancel.")


class GenUIVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Canvas source version identifier.")
    parent_version_id = serializers.UUIDField(
        allow_null=True,
        help_text="Canvas source version this version was based on.",
    )
    version = serializers.IntegerField(min_value=1, help_text="One-based version number within this visualization.")
    operation = serializers.ChoiceField(
        choices=["initial", "regenerate", "improve", "source_edit"],
        help_text="Action that created this version.",
    )
    prompt = serializers.CharField(help_text="Prompt or change note entered for this version.")
    effective_prompt = serializers.CharField(help_text="Complete prompt represented by this version.")
    model = serializers.CharField(
        allow_null=True,
        help_text="AI model used for this version, or null for imported and manually edited versions.",
    )
    created_at = serializers.DateTimeField(help_text="When this version was created.")
    build_status = serializers.ChoiceField(
        choices=["queued", "building", "ready", "failed"],
        allow_null=True,
        help_text="Latest Canvas build state for this source version.",
    )
    artifact_url = serializers.URLField(
        allow_null=True,
        help_text="Short-lived artifact URL for previewing this version when a retained build is available.",
    )


class GenUIStatusSerializer(serializers.Serializer):
    lifecycle_status = serializers.ChoiceField(
        choices=["awaiting_generation", "generating", "building", "ready", "failed"],
        help_text="Current visualization state derived from its Canvas build.",
    )
    error_detail = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Actionable detail when visualization generation or building failed.",
    )
    artifact_url = serializers.URLField(
        required=False,
        allow_null=True,
        help_text="Short-lived URL for the current visualization artifact.",
    )
    frame_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Dataframes the current visualization may read.",
    )
    generation_started_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When the active or most recent generation started.",
    )
    generation_id = serializers.UUIDField(
        allow_null=True,
        help_text="Cancelable generation identifier while model generation is active.",
    )
    current_version_id = serializers.UUIDField(
        allow_null=True,
        help_text="Canvas source version currently selected as the visualization head.",
    )
    versions = GenUIVersionSerializer(many=True, help_text="Complete source-version history, oldest first.")


class GenUISourceResponseSerializer(serializers.Serializer):
    version_id = serializers.UUIDField(help_text="Source version returned by this response.")
    current_version_id = serializers.UUIDField(help_text="Current source version used for optimistic concurrency.")
    source = serializers.CharField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        help_text="Complete editable src/canvas.tsx source for this version."
    )


class GenUISourceQuerySerializer(serializers.Serializer):
    version_id = serializers.UUIDField(
        required=False,
        help_text="Historical source version to return instead of the current version.",
    )


class GenUISourceSaveRequestSerializer(serializers.Serializer):
    source = serializers.CharField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        trim_whitespace=False,
        help_text="Complete replacement src/canvas.tsx source.",
    )
    prompt = serializers.CharField(
        max_length=20_000,
        trim_whitespace=False,
        help_text="Change note stored with the new source version.",
    )
    expected_current_version_id = serializers.UUIDField(
        help_text="Current version the source edit is based on.",
    )


class GenUIRevertRequestSerializer(serializers.Serializer):
    version_id = serializers.UUIDField(help_text="Historical source version to restore.")
    expected_current_version_id = serializers.UUIDField(
        help_text="Current version observed before requesting the restore.",
    )


class GenUIErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable machine-readable error code.")
    detail = serializers.CharField(help_text="Error detail with a next action.")


class GenUIInputColumnSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Dataframe column name.")
    type = serializers.CharField(help_text="Dataframe column type reported by the notebook run.")


@extend_schema_field(OpenApiTypes.ANY)
class GenUIFrameCellField(serializers.Field):
    def to_representation(self, value: object) -> object:
        return value


class GenUIFrameSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Dataframe name.")
    columns = GenUIInputColumnSerializer(many=True, help_text="Dataframe columns and types.")
    rows = serializers.ListField(
        child=serializers.ListField(child=GenUIFrameCellField()),
        help_text="Bounded, JSON-safe preview rows from the latest successful cell run.",
    )
    totalRowCount = serializers.IntegerField(min_value=0, help_text="Total rows reported by the notebook run.")
    includedRowCount = serializers.IntegerField(min_value=0, help_text="Rows included in this response.")
    truncated = serializers.BooleanField(help_text="Whether rows were omitted from this response.")
