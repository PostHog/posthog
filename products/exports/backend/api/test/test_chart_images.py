import io
import base64

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from PIL import Image

from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.models.insight import Insight


class TestChartImagesAPI(APIBaseTest):
    def _png_base64(self, color: str = "blue", size: tuple[int, int] = (8, 8)) -> str:
        buffer = io.BytesIO()
        Image.new("RGB", size, color).save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    def _publish(self, **payload):
        return self.client.post(f"/api/projects/{self.team.id}/chart_images/", payload)

    def test_publish_returns_durable_image_url(self):
        response = self._publish(image_base64=self._png_base64(), title="Weekly signups")
        assert response.status_code == 201, response.content
        body = response.json()
        assert "/exporter/" in body["image_url"]
        assert ".png" in body["image_url"]
        assert "token=" in body["image_url"]
        asset = ExportedAsset.objects.get(pk=body["id"])
        assert asset.team == self.team
        assert asset.export_format == ExportedAsset.ExportFormat.PNG
        assert asset.has_content

    def test_publish_links_insight_for_provenance(self):
        insight = Insight.objects.create(
            team=self.team, short_id="abc123", name="Signups", query={"kind": "TrendsQuery"}, created_by=self.user
        )
        response = self._publish(image_base64=self._png_base64(), insight_short_id="abc123")
        assert response.status_code == 201, response.content
        assert ExportedAsset.objects.get(pk=response.json()["id"]).insight_id == insight.id

    def test_publish_rejects_unknown_insight(self):
        response = self._publish(image_base64=self._png_base64(), insight_short_id="nope99")
        assert response.status_code == 400

    def test_publish_rejects_non_png(self):
        response = self._publish(image_base64=base64.b64encode(b"this is definitely not a png file").decode())
        assert response.status_code == 400

    def test_publish_rejects_invalid_base64(self):
        response = self._publish(image_base64="!!!not-base64!!!")
        assert response.status_code == 400

    def test_publish_rejects_oversized_image(self):
        with patch("products.exports.backend.api.chart_images.MAX_IMAGE_BYTES", 10):
            response = self._publish(image_base64=self._png_base64())
        assert response.status_code == 400
