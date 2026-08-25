from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class GenUIGenerateRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=20_000,
        trim_whitespace=False,
        help_text="Instructions for the generated visualization.",
    )
    inputs = serializers.ListField(
        child=serializers.CharField(max_length=128),
        max_length=4,
        help_text="Dataframe names the generated visualization may read.",
    )


class GenUIStatusSerializer(serializers.Serializer):
    lifecycle_status = serializers.ChoiceField(
        choices=["awaiting_generation", "building", "ready", "failed"],
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
