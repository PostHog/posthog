from rest_framework import serializers

from products.notebooks.backend.presentation.widget_serializers import (
    WidgetInputBindingsField,
    WidgetInputContractItemSerializer,
    WidgetSecurityReviewSerializer,
)


class WidgetSnapshotRequestSerializer(serializers.Serializer):
    node_id = serializers.CharField(max_length=128, help_text="Notebook widget node to add to a dashboard.")
    version_id = serializers.UUIDField(help_text="Immutable widget version to keep on the dashboard.")
    notebook_run_id = serializers.UUIDField(
        required=False, help_text="Completed whole-notebook run supplying every input after refresh."
    )
    previous_snapshot_id = serializers.UUIDField(
        required=False, help_text="Snapshot being refreshed; its version and input mappings must match."
    )


class WidgetSnapshotSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Immutable snapshot containing the widget's saved dataframe results.")
    node_id = serializers.CharField(help_text="Source widget node in the notebook.")
    version_id = serializers.UUIDField(help_text="Pinned generated widget version.")
    created_at = serializers.DateTimeField(help_text="When all dataframe results were saved.")
    frame_names = serializers.ListField(child=serializers.CharField(), help_text="Allowed dataframe slots.")
    input_bindings = WidgetInputBindingsField(help_text="Frozen input mappings and Hog transforms.")
    input_contract = WidgetInputContractItemSerializer(many=True, help_text="Pinned widget input schemas.")
    artifact_url = serializers.URLField(allow_null=True, help_text="Short-lived URL for the pinned widget build.")
    build_hash = serializers.CharField(allow_null=True, help_text="Exact build hash used for execution consent.")
    security_review = WidgetSecurityReviewSerializer(allow_null=True, help_text="Review of the pinned widget source.")
