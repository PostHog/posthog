import io

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from asgiref.sync import sync_to_async
from parameterized import parameterized
from PIL import Image

from products.web_analytics.backend.heatmap_screenshot_grounding import (
    _annotate,
    _build_markers,
    _fetch_screenshot_bytes,
    ground_heatmap_hotspots,
)
from products.web_analytics.backend.models import HeatmapSnapshot, SavedHeatmap

_GROUND_PATH = "products.web_analytics.backend.heatmap_screenshot_grounding._ground"


def _jpeg(width: int = 200, height: int = 300) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(buf, format="JPEG")
    return buf.getvalue()


def _heatmap_data(*, clicks: int = 1, rage: int = 1) -> dict:
    return {
        "clicks": [{"pointer_relative_x": 0.5, "pointer_y": 100, "count": 5}] * clicks,
        "rageclicks": [{"pointer_relative_x": 0.8, "pointer_y": 150, "count": 3}] * rage,
    }


class TestMarkersAndAnnotation(SimpleTestCase):
    def test_build_markers_puts_rage_first_and_skips_zero_count(self):
        data = {
            "clicks": [{"pointer_relative_x": 0.5, "pointer_y": 100, "count": 16}],
            "rageclicks": [
                {"pointer_relative_x": 0.83, "pointer_y": 600, "count": 4},
                {"pointer_relative_x": 0.1, "pointer_y": 50, "count": 0},
            ],
        }
        markers = _build_markers(data)
        assert [(m.n, m.kind, m.count) for m in markers] == [(1, "rage", 4), (2, "click", 16)]

    def test_annotate_clamps_out_of_bounds_and_returns_valid_jpeg(self):
        markers = _build_markers({"rageclicks": [{"pointer_relative_x": 1.5, "pointer_y": 999_999, "count": 2}]})
        out = _annotate(_jpeg(200, 300), markers)
        assert Image.open(io.BytesIO(out)).format == "JPEG"


class TestFetchScreenshotBytes(APIBaseTest):
    def _saved(self, **overrides) -> SavedHeatmap:
        fields = {
            "team": self.team,
            "url": "https://posthog.com/pricing",
            "type": SavedHeatmap.Type.SCREENSHOT,
            "status": SavedHeatmap.Status.COMPLETED,
            "deleted": False,
            **overrides,
        }
        return SavedHeatmap.objects.create(**fields)

    def test_returns_bytes_for_matching_screenshot(self):
        saved = self._saved()
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=_jpeg())

        result = _fetch_screenshot_bytes(self.team, "https://posthog.com/pricing")

        assert result is not None
        assert len(result[0]) > 0 and result[1] == saved.created_at

    @parameterized.expand(
        [
            ("wrong_type", {"type": SavedHeatmap.Type.IFRAME}, True),
            ("deleted", {"deleted": True}, True),
            ("url_mismatch", {"url": "https://posthog.com/other"}, True),
            ("not_completed", {"status": SavedHeatmap.Status.FAILED}, True),
        ]
    )
    def test_excludes_unusable_screenshots(self, _name, overrides, with_content):
        saved = self._saved(**overrides)
        if with_content:
            HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=_jpeg())

        assert _fetch_screenshot_bytes(self.team, "https://posthog.com/pricing") is None

    def test_returns_none_when_snapshot_has_no_inline_content(self):
        saved = self._saved()
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=None, content_location="s3://x")

        assert _fetch_screenshot_bytes(self.team, "https://posthog.com/pricing") is None

    def test_newer_contentless_screenshot_does_not_mask_older_usable_one(self):
        older = self._saved()
        HeatmapSnapshot.objects.create(heatmap=older, width=1024, content=_jpeg())
        newer = self._saved()
        HeatmapSnapshot.objects.create(heatmap=newer, width=1024, content=None, content_location="s3://x")

        result = _fetch_screenshot_bytes(self.team, "https://posthog.com/pricing")

        assert result is not None
        assert result[1] == older.created_at


class TestGroundHeatmapHotspots(APIBaseTest):
    @sync_to_async
    def _seed_screenshot(self, url: str = "https://posthog.com/pricing") -> None:
        saved = SavedHeatmap.objects.create(
            team=self.team, url=url, type=SavedHeatmap.Type.SCREENSHOT, status=SavedHeatmap.Status.COMPLETED
        )
        HeatmapSnapshot.objects.create(heatmap=saved, width=1024, content=_jpeg())

    async def test_returns_none_when_no_cached_screenshot(self):
        result = await ground_heatmap_hotspots(
            self.team, self.user, page_url="https://posthog.com/pricing", heatmap_data=_heatmap_data()
        )
        assert result is None

    async def test_degrades_to_none_when_vision_call_fails(self):
        await self._seed_screenshot()
        with patch(_GROUND_PATH, side_effect=RuntimeError("gateway down")):
            result = await ground_heatmap_hotspots(
                self.team, self.user, page_url="https://posthog.com/pricing", heatmap_data=_heatmap_data()
            )
        assert result is None

    async def test_returns_grounding_when_vision_succeeds(self):
        await self._seed_screenshot()
        with patch(_GROUND_PATH, return_value="#1: disabled Start trial button"):
            result = await ground_heatmap_hotspots(
                self.team, self.user, page_url="https://posthog.com/pricing", heatmap_data=_heatmap_data()
            )
        assert result is not None
        assert result.grounded_text == "#1: disabled Start trial button"
        assert len(result.annotated_image_b64) > 0
        assert [(m["n"], m["kind"]) for m in result.markers] == [(1, "rage"), (2, "click")]
