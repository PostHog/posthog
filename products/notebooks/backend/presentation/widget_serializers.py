from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.notebooks.backend.models import GeneratedWidget
from products.notebooks.backend.widget_models import DEFAULT_WIDGET_MODEL, WIDGET_MODEL_CHOICES


class WidgetGenerateRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=20_000,
        trim_whitespace=False,
        help_text="Instructions for the generated widget.",
    )
    generation_id = serializers.UUIDField(help_text="Idempotency key for this generation job.")
    model = serializers.ChoiceField(
        choices=WIDGET_MODEL_CHOICES,
        default=DEFAULT_WIDGET_MODEL,
        help_text="AI model used to generate the widget.",
    )
    operation = serializers.ChoiceField(
        choices=["initial", "regenerate", "improve"],
        default="regenerate",
        help_text="Whether to generate from scratch or improve the current source.",
    )


class WidgetCancelRequestSerializer(serializers.Serializer):
    generation_id = serializers.UUIDField(help_text="Generation job to cancel.")


class WidgetJobSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Generation job identifier.")
    status = serializers.ChoiceField(
        choices=["queued", "generating", "publishing"],
        help_text="Current durable job state.",
    )
    phase = serializers.CharField(help_text="Current generation phase.")
    model = serializers.CharField(help_text="AI model processing the job.")
    created_at = serializers.DateTimeField(help_text="When the job was queued.")
    started_at = serializers.DateTimeField(allow_null=True, help_text="When a worker started the job.")


class WidgetStatusSerializer(serializers.Serializer):
    lifecycle_status = serializers.ChoiceField(
        choices=["awaiting_generation", "generating", "building", "ready", "failed", "incompatible"],
        help_text="Current widget and preview state.",
    )
    error_detail = serializers.CharField(required=False, allow_null=True, help_text="Actionable failure detail.")
    artifact_url = serializers.URLField(
        required=False,
        allow_null=True,
        help_text="Short-lived URL for the selected widget version's preview.",
    )
    frame_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Logical dataframe slots available to the selected version.",
    )
    current_version_id = serializers.UUIDField(allow_null=True, help_text="Selected immutable widget version.")
    widget_id = serializers.UUIDField(allow_null=True, help_text="Reusable widget identity.")
    instance_id = serializers.UUIDField(allow_null=True, help_text="Placement in this notebook.")
    has_versions = serializers.BooleanField(help_text="Whether the widget has generated history.")
    active_job = WidgetJobSerializer(allow_null=True, help_text="Active generation job, if any.")


class WidgetVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Immutable widget version identifier.")
    parent_version_id = serializers.UUIDField(allow_null=True, help_text="Version this one was based on.")
    version = serializers.IntegerField(min_value=1, help_text="One-based version number.")
    operation = serializers.ChoiceField(
        choices=["initial", "regenerate", "improve", "source_edit", "revert"],
        help_text="Action that created this version.",
    )
    prompt_delta = serializers.CharField(help_text="Instructions added by this version.")
    model = serializers.CharField(allow_null=True, help_text="AI model, or null for manual changes.")
    created_at = serializers.DateTimeField(help_text="When this version was created.")
    build_status = serializers.ChoiceField(
        choices=["queued", "building", "ready", "failed"],
        allow_null=True,
        help_text="Preview build state.",
    )
    artifact_url = serializers.URLField(allow_null=True, help_text="Preview URL when retained and ready.")
    frame_names = serializers.ListField(
        child=serializers.CharField(), help_text="Logical dataframe slots available to this version."
    )
    is_current = serializers.BooleanField(help_text="Whether this notebook instance currently displays this version.")


class WidgetVersionPageSerializer(serializers.Serializer):
    results = WidgetVersionSerializer(many=True, help_text="Versions ordered newest first.")
    count = serializers.IntegerField(min_value=0, help_text="Total versions.")
    next_offset = serializers.IntegerField(allow_null=True, help_text="Offset for the next page.")


class WidgetVersionQuerySerializer(serializers.Serializer):
    offset = serializers.IntegerField(default=0, min_value=0)
    limit = serializers.IntegerField(default=25, min_value=1, max_value=100)


class WidgetSourceResponseSerializer(serializers.Serializer):
    version_id = serializers.UUIDField(help_text="Version returned by this response.")
    current_version_id = serializers.UUIDField(help_text="Current version used for optimistic concurrency.")
    source = serializers.CharField(help_text="Complete editable src/canvas.tsx source.")  # type: ignore[assignment]
    effective_prompt = serializers.CharField(help_text="Instructions materialized from this version's lineage.")


class WidgetSourceQuerySerializer(serializers.Serializer):
    version_id = serializers.UUIDField(required=False, help_text="Historical version to return.")


class WidgetSourceSaveRequestSerializer(serializers.Serializer):
    source = serializers.CharField(trim_whitespace=False, help_text="Complete replacement source.")  # type: ignore[assignment]
    prompt = serializers.CharField(max_length=20_000, trim_whitespace=False, help_text="Description of the change.")
    expected_current_version_id = serializers.UUIDField(help_text="Version the edit is based on.")


class WidgetRevertRequestSerializer(serializers.Serializer):
    version_id = serializers.UUIDField(help_text="Earlier version to restore as a new version.")
    expected_current_version_id = serializers.UUIDField(help_text="Current version used for optimistic concurrency.")


class WidgetFrameQuerySerializer(serializers.Serializer):
    version_id = serializers.UUIDField(required=False, help_text="Version requesting the data.")
    offset = serializers.IntegerField(default=0, min_value=0, help_text="Zero-based row offset.")
    limit = serializers.IntegerField(default=100, min_value=1, max_value=500, help_text="Maximum rows in this page.")


class WidgetFrameColumnSerializer(serializers.Serializer):
    name = serializers.CharField()
    type = serializers.CharField()


class WidgetFrameSerializer(serializers.Serializer):
    name = serializers.CharField()
    columns = WidgetFrameColumnSerializer(many=True)
    rows = serializers.ListField(child=serializers.ListField(child=serializers.JSONField()))
    totalRowCount = serializers.IntegerField(min_value=0)
    includedRowCount = serializers.IntegerField(min_value=0)
    offset = serializers.IntegerField(min_value=0)
    nextOffset = serializers.IntegerField(min_value=0, allow_null=True)
    truncated = serializers.BooleanField()


class WidgetErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable machine-readable error code.")
    detail = serializers.CharField(help_text="Actionable error detail.")


class WidgetCatalogSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    current_version_id = serializers.UUIDField(allow_null=True, read_only=True)
    usage_count = serializers.SerializerMethodField(help_text="Notebook instances linked to this widget.")
    version_count = serializers.SerializerMethodField(help_text="Immutable versions retained for this widget.")

    class Meta:
        model = GeneratedWidget
        fields = [
            "id",
            "name",
            "description",
            "visibility",
            "current_version_id",
            "version_count",
            "usage_count",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.INT)
    def get_usage_count(self, obj: GeneratedWidget) -> int:
        annotated = getattr(obj, "usage_count", None)
        return int(annotated) if annotated is not None else obj.notebook_instances.count()

    @extend_schema_field(OpenApiTypes.INT)
    def get_version_count(self, obj: GeneratedWidget) -> int:
        annotated = getattr(obj, "version_count", None)
        return int(annotated) if annotated is not None else obj.versions.count()
