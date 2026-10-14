from typing import Any

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


class WidgetSnapshotPublishSerializer(WidgetSnapshotRequestSerializer):
    dashboard_id = serializers.IntegerField(required=False, min_value=1, help_text="Dashboard to add the widget to.")
    tile_id = serializers.IntegerField(required=False, min_value=1, help_text="Existing dashboard tile to refresh.")
    name = serializers.CharField(
        required=False, max_length=400, default="", help_text="Title for a new dashboard widget."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("dashboard_id" in attrs) == ("tile_id" in attrs):
            raise serializers.ValidationError("Choose a dashboard to add to or a tile to refresh.")
        if "tile_id" in attrs and ("previous_snapshot_id" not in attrs or "notebook_run_id" not in attrs):
            raise serializers.ValidationError("Refreshing requires the previous snapshot and a completed notebook run.")
        return attrs


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
