import base64
import binascii
from datetime import timedelta
from typing import Any

from django.utils.timezone import now

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import mixins, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.exports.backend.models.exported_asset import ExportedAsset, save_content
from products.product_analytics.backend.models.insight import Insight

CHART_IMAGE_TTL_DAYS = 30
MAX_IMAGE_BYTES = 5 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ChartImageSerializer(serializers.Serializer):
    image_base64 = serializers.CharField(
        write_only=True,
        help_text="Base64-encoded PNG image bytes to publish. Must decode to a PNG no larger than 5 MiB.",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional title used to build a readable filename for the published image.",
    )
    insight_short_id = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Optional short id of the insight this image visualizes, recorded for provenance.",
    )
    id = serializers.IntegerField(read_only=True, help_text="Id of the published image asset.")
    image_url = serializers.SerializerMethodField(
        help_text="Durable signed URL of the published PNG, fetchable without authentication so it can be posted to Slack.",
    )

    @extend_schema_field(OpenApiTypes.URI)
    def get_image_url(self, asset: ExportedAsset) -> str:
        return asset.get_subscription_delivery_content_url()

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            png = base64.b64decode(data["image_base64"], validate=True)
        except (binascii.Error, ValueError):
            raise serializers.ValidationError({"image_base64": "Must be valid base64."})
        if len(png) > MAX_IMAGE_BYTES:
            raise serializers.ValidationError({"image_base64": f"Image exceeds the {MAX_IMAGE_BYTES} byte limit."})
        if png[:8] != PNG_MAGIC:
            raise serializers.ValidationError({"image_base64": "Decoded bytes are not a PNG image."})
        data["image_bytes"] = png
        return data

    def create(self, validated_data: dict[str, Any]) -> ExportedAsset:
        team = self.context["get_team"]()
        asset = ExportedAsset.objects.create(
            team=team,
            insight=self._resolve_insight(team, validated_data.get("insight_short_id")),
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context={"filename": validated_data.get("title") or "chart"},
            expires_after=now() + timedelta(days=CHART_IMAGE_TTL_DAYS),
        )
        save_content(asset, validated_data["image_bytes"])
        return asset

    def _resolve_insight(self, team: Any, short_id: str | None) -> Insight | None:
        if not short_id:
            return None
        insight = Insight.objects.filter(team=team, short_id=short_id).first()
        if insight is None:
            raise serializers.ValidationError({"insight_short_id": "No insight found with this short id."})
        return insight


@extend_schema(
    extensions={"x-product": "exports"},
    description="Publish a pre-rendered PNG image and get back a durable signed URL that can be posted to Slack.",
)
class ChartImageViewSet(TeamAndOrgViewSetMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    scope_object = "export"
    queryset = ExportedAsset.objects.all()
    serializer_class = ChartImageSerializer
