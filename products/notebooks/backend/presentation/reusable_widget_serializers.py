from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from products.notebooks.backend.presentation.widget_serializers import (
    WidgetFrameSerializer,
    WidgetGenerateRequestSerializer,
    WidgetInputBindingsField,
    WidgetInputContractItemSerializer,
    WidgetSecurityReviewSerializer,
)


class ReusableWidgetPublishRequestSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=400,
        help_text="Name shown in the reusable widget catalog.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2_000,
        help_text="Short explanation of what the reusable widget shows and when to use it.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        max_length=10,
        help_text="Searchable labels attached to the reusable widget.",
    )

    def validate_tags(self, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw_tag in value:
            tag = raw_tag.strip()
            folded = tag.casefold()
            if tag and folded not in seen:
                result.append(tag)
                seen.add(folded)
        return result


class ReusableWidgetAttachRequestSerializer(serializers.Serializer):
    widget_id = serializers.UUIDField(help_text="Reusable widget to place in this notebook node.")
    version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Version to pin, or null to follow the reusable widget's latest version.",
    )
    input_bindings = WidgetInputBindingsField(
        required=False,
        default=dict,
        help_text=(
            "Notebook-local input mappings keyed by contract slot. Each value names a source dataframe and may "
            "include a pure Hog expression plus compiled bytecode for reshaping its rows."
        ),
    )


ReusableWidgetGenerateRequestSerializer = WidgetGenerateRequestSerializer


class ReusableWidgetCatalogQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=200,
        help_text="Case-insensitive search across reusable widget names, descriptions, and tags.",
    )
    offset = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Zero-based result offset.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        max_value=100,
        help_text="Maximum number of reusable widgets to return.",
    )


class ReusableWidgetSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable reusable widget identifier.")
    name = serializers.CharField(help_text="Catalog name of the reusable widget.")
    description = serializers.CharField(help_text="Description of the reusable widget.")
    tags = serializers.ListField(child=serializers.CharField(), help_text="Searchable widget labels.")
    publication_status = serializers.ChoiceField(
        choices=["published", "deprecated"],
        help_text="Catalog lifecycle of the reusable widget.",
    )
    current_version_id = serializers.UUIDField(help_text="Current immutable version used by unpinned instances.")
    version_count = serializers.IntegerField(help_text="Number of immutable versions in this widget's history.")
    instance_count = serializers.IntegerField(help_text="Number of notebook placements using this widget.")
    created_at = serializers.DateTimeField(help_text="When the widget identity was created.")
    published_at = serializers.DateTimeField(help_text="When the widget became reusable.")
    updated_at = serializers.DateTimeField(help_text="When the reusable widget was last changed.")


@extend_schema_serializer(many=False)
class ReusableWidgetPageSerializer(serializers.Serializer):
    results = ReusableWidgetSummarySerializer(many=True, help_text="Reusable widgets in this page.")
    count = serializers.IntegerField(help_text="Total reusable widgets matching the search.")
    next_offset = serializers.IntegerField(
        allow_null=True,
        help_text="Offset for the next page, or null when this is the final page.",
    )


class ReusableWidgetVersionDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Immutable widget version identifier.")
    title = serializers.CharField(help_text="Title stored with this version.")
    version = serializers.IntegerField(help_text="One-based version number.")
    operation = serializers.ChoiceField(
        choices=["initial", "regenerate", "improve", "revert"],
        help_text="Action that created this version.",
    )
    model = serializers.CharField(
        allow_null=True,
        help_text="AI model that created this version, or null when none was recorded.",
    )
    artifact_url = serializers.URLField(
        allow_null=True,
        help_text="Short-lived URL for the current widget preview.",
    )
    build_status = serializers.ChoiceField(
        choices=["queued", "building", "ready", "failed"],
        allow_null=True,
        help_text="Preview build state.",
    )
    build_hash = serializers.CharField(
        allow_null=True,
        help_text="SHA-256 integrity hash for the immutable preview artifact.",
    )
    frame_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Logical dataframe slots accepted by this widget version.",
    )
    input_contract = WidgetInputContractItemSerializer(
        many=True,
        help_text="Dataframe slots and schemas expected by this widget version.",
    )
    security_review = WidgetSecurityReviewSerializer(
        allow_null=True,
        help_text="Automated source review for this version, if available.",
    )
    has_demo_data = serializers.BooleanField(help_text="Whether this version has saved demo data.")
    created_at = serializers.DateTimeField(help_text="When this immutable version was created.")


class ReusableWidgetDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable reusable widget identifier.")
    name = serializers.CharField(help_text="Catalog name of the reusable widget.")
    description = serializers.CharField(help_text="Description of the reusable widget.")
    tags = serializers.ListField(child=serializers.CharField(), help_text="Searchable widget labels.")
    publication_status = serializers.ChoiceField(
        choices=["published", "deprecated"],
        help_text="Catalog lifecycle of the reusable widget.",
    )
    current_version = ReusableWidgetVersionDetailSerializer(help_text="Current reusable widget version.")
    version_count = serializers.IntegerField(help_text="Number of immutable versions in this widget's history.")
    instance_count = serializers.IntegerField(help_text="Number of notebook placements using this widget.")
    created_at = serializers.DateTimeField(help_text="When the widget identity was created.")
    published_at = serializers.DateTimeField(help_text="When the widget became reusable.")
    updated_at = serializers.DateTimeField(help_text="When the reusable widget was last changed.")


__all__ = [
    "ReusableWidgetCatalogQuerySerializer",
    "ReusableWidgetAttachRequestSerializer",
    "ReusableWidgetDetailSerializer",
    "ReusableWidgetGenerateRequestSerializer",
    "ReusableWidgetPageSerializer",
    "ReusableWidgetPublishRequestSerializer",
    "WidgetFrameSerializer",
]
