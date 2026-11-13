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


class SiteStyleSerializer(serializers.Serializer):
    background_color = serializers.CharField(help_text="Hex color of the page surface behind its main content.")
    text_color = serializers.CharField(help_text="Hex color of the page's main text.")
    button_color = serializers.CharField(
        allow_null=True, help_text="Hex background color of the page's most prominent button. Null when none was found."
    )
    button_text_color = serializers.CharField(
        allow_null=True, help_text="Hex text color of that button. Null when no button was found."
    )
    button_border_radius = serializers.IntegerField(
        allow_null=True, help_text="Corner radius of that button in CSS pixels. Null when no button was found."
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
    site_style = SiteStyleSerializer(
        allow_null=True,
        help_text=(
            "Colors read from the snapshot's page, to suggest a survey appearance that matches the site. "
            "Null until the snapshot is ready, or when the page's colors could not be read."
        ),
    )
