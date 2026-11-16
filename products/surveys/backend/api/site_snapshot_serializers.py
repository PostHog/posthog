from rest_framework import serializers

from products.surveys.backend.site_snapshot import DEVICE_VIEWPORTS, SnapshotDevice, SnapshotStatus


class SiteSnapshotQuerySerializer(serializers.Serializer):
    device = serializers.ChoiceField(
        choices=SnapshotDevice.choices,
        help_text=(
            f"Which viewport to show. Desktop picks a page viewed in a window at least "
            f"{DEVICE_VIEWPORTS[SnapshotDevice.DESKTOP].min_width}px wide, mobile one at most "
            f"{DEVICE_VIEWPORTS[SnapshotDevice.MOBILE].max_width}px wide."
        ),
    )


class SiteSnapshotSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=SnapshotStatus.choices,
        help_text=(
            "`ready` when the snapshot image can be loaded, `rendering` while it is being created, "
            "`unavailable` when no recent session recording matches the survey or the user cannot view recordings."
        ),
    )
    exported_asset_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the exported image. Load it from the exports content endpoint once the status is `ready`.",
    )
    page_url = serializers.CharField(
        allow_null=True,
        help_text="URL of the page the snapshot shows. Null when the status is `unavailable`.",
    )
    viewport_width = serializers.IntegerField(
        allow_null=True,
        help_text="Width in CSS pixels of the browser window the snapshot was recorded in, to draw it at its real scale.",
    )
