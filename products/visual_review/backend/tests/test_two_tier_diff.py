"""Tests for two-tier diff classification (pixelmatch + SSIM)."""

import io

import pytest

import numpy as np
from PIL import Image, ImageDraw

from products.visual_review.backend.diff import compare_images
from products.visual_review.backend.diffing import (
    PIXEL_DIFF_THRESHOLD_PERCENT,
    SSIM_DISSIMILARITY_THRESHOLD,
    classify_compare_result,
)
from products.visual_review.backend.facade.enums import ChangeKind


def _make_png(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_tall_settings_page(width: int = 400, height: int = 3000, extra_element: bool = False) -> bytes:
    """Build a synthetic tall settings page with varied UI structure.

    Simulates cards with text blocks, buttons, and dividers — enough
    structural complexity for SSIM to be meaningful.
    """
    img = Image.new("RGBA", (width, height), (245, 245, 245, 255))
    draw = ImageDraw.Draw(img)
    rng = np.random.RandomState(42)

    y = 20
    for _ in range(35):
        card_h = rng.randint(40, 80)
        draw.rectangle([(20, y), (width - 20, y + card_h)], fill=(255, 255, 255, 255), outline=(220, 220, 220, 255))
        for line_y in range(y + 10, y + card_h - 10, 14):
            tw = rng.randint(100, 300)
            draw.rectangle([(30, line_y), (30 + tw, line_y + 8)], fill=(80, 80, 80, 255))
        if rng.random() > 0.6:
            draw.rectangle([(width - 120, y + 10), (width - 30, y + 35)], fill=(50, 100, 200, 255))
        y += card_h + 15

    if extra_element:
        btn_y = y + 10
        draw.rectangle([(20, btn_y), (width - 20, btn_y + 45)], fill=(255, 243, 224, 255), outline=(200, 160, 100, 255))
        draw.rectangle([(30, btn_y + 12), (250, btn_y + 32)], fill=(200, 100, 50, 255))
        draw.rectangle([(260, btn_y + 12), (370, btn_y + 32)], fill=(100, 160, 50, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _classify(baseline_bytes: bytes, current_bytes: bytes) -> ChangeKind | None:
    """Run the production classifier on a fresh compare result."""
    result = compare_images(baseline_bytes, current_bytes, with_thumbnail=False)
    return classify_compare_result(result)


class TestTwoTierClassification:
    """Tests for the combined pixelmatch + SSIM classification.

    The two-tier approach addresses tall-page dilution: a real UI change
    at the bottom of a long screenshot affects few pixels (below
    pixelmatch's 1% threshold) but produces a measurable structural
    shift that SSIM catches.
    """

    @pytest.mark.parametrize(
        "baseline_color, current_color, expected_kind",
        [
            pytest.param((255, 0, 0, 255), (0, 0, 255, 255), ChangeKind.PIXEL, id="obvious_pixel_change"),
            pytest.param((100, 100, 100, 255), (100, 100, 100, 255), None, id="identical"),
            pytest.param((100, 100, 100, 255), (105, 100, 100, 255), None, id="subtle_noise"),
        ],
    )
    def test_solid_color_classification(
        self,
        baseline_color: tuple[int, int, int, int],
        current_color: tuple[int, int, int, int],
        expected_kind: ChangeKind | None,
    ):
        baseline = _make_png(100, 100, baseline_color)
        current = _make_png(100, 100, current_color)
        assert _classify(baseline, current) == expected_kind

    def test_tall_page_change_caught_by_ssim(self):
        baseline = _make_tall_settings_page(extra_element=False)
        current = _make_tall_settings_page(extra_element=True)

        result = compare_images(baseline, current, with_thumbnail=False)
        assert result.diff_percentage < PIXEL_DIFF_THRESHOLD_PERCENT

        ssim_dissimilarity = 1.0 - result.ssim_score
        assert ssim_dissimilarity > SSIM_DISSIMILARITY_THRESHOLD

        assert _classify(baseline, current) == ChangeKind.STRUCTURAL

    def test_size_mismatch_still_classifies_normally(self):
        # Pixelhog pads to the bigger size and runs metrics over the
        # padded buffers — we still get a real pixel-tier classification
        # (the new content area shows up as differing pixels). The fact
        # that sizes differed is recorded separately on diff_metadata.
        small = _make_png(100, 100, (200, 200, 200, 255))
        large = _make_png(200, 100, (200, 200, 200, 255))
        result = compare_images(small, large, with_thumbnail=False)
        assert result.size_mismatch
        assert _classify(small, large) == ChangeKind.PIXEL

    def test_compare_images_populates_ssim_score_for_every_path(self):
        # ssim_score is now the source of truth for structural similarity —
        # not derived after the fact, not overwritten by the classifier.
        # A pixel-tier diff still has a meaningful SSIM number alongside.
        red = _make_png(100, 100, (255, 0, 0, 255))
        blue = _make_png(100, 100, (0, 0, 255, 255))
        result = compare_images(red, blue, with_thumbnail=False)
        assert 0.0 <= result.ssim_score <= 1.0
        assert result.ssim_score < 0.8  # red vs blue is structurally different


class TestClusterSummary:
    """Cluster output is meaningful for localized diffs only — not for
    full inversions, not for identical pairs.
    """

    def test_localized_change_yields_clusters(self):
        # Same baseline and current except for a small block in the middle.
        base = _make_png(200, 200, (240, 240, 240, 255))
        cur_img = Image.open(io.BytesIO(base))
        ImageDraw.Draw(cur_img).rectangle([90, 90, 110, 110], fill=(255, 0, 0, 255))
        buf = io.BytesIO()
        cur_img.save(buf, format="PNG")

        result = compare_images(base, buf.getvalue(), with_thumbnail=False)
        assert result.cluster_summary is not None
        assert result.cluster_summary.total >= 1
        assert len(result.cluster_summary.items) >= 1
        # Bbox should land near the drawn rectangle (90,90)+20×20, with
        # tolerance for the dilation that grows the bbox outward in
        # every direction.
        c = result.cluster_summary.items[0]
        x, y, w, h = c.bbox
        assert 76 <= x <= 92 and 76 <= y <= 92
        assert 18 <= w <= 40 and 18 <= h <= 40
        assert c.px > 0
        assert 0 <= c.centroid[0] <= 200 and 0 <= c.centroid[1] <= 200

    def test_size_mismatch_yields_clusters_for_new_content_area(self):
        # Pixelhog pads to the bigger size; the new content area
        # surfaces as a cluster of its own. That's the right answer
        # ("here's the new region") rather than something to hide.
        small = _make_png(100, 100, (200, 200, 200, 255))
        large = _make_png(200, 100, (200, 200, 200, 255))
        result = compare_images(small, large, with_thumbnail=False)
        assert result.size_mismatch
        assert result.cluster_summary is not None
        assert result.cluster_summary.total >= 1

    def test_identical_images_have_no_clusters(self):
        img = _make_png(100, 100, (200, 200, 200, 255))
        result = compare_images(img, img, with_thumbnail=False)
        assert result.cluster_summary is None  # diff_pixel_count is 0, skipped

    def test_with_clusters_false_skips_computation(self):
        red = _make_png(100, 100, (255, 0, 0, 255))
        blue = _make_png(100, 100, (0, 0, 255, 255))
        result = compare_images(red, blue, with_thumbnail=False, with_clusters=False)
        assert result.cluster_summary is None

    def test_diff_metadata_pydantic_round_trip(self):
        # Storage round-trip: dump -> load yields the same shape.
        from products.visual_review.backend.diff_metadata import DiffMetadata

        base = _make_png(200, 200, (240, 240, 240, 255))
        cur_img = Image.open(io.BytesIO(base))
        ImageDraw.Draw(cur_img).rectangle([90, 90, 110, 110], fill=(255, 0, 0, 255))
        buf = io.BytesIO()
        cur_img.save(buf, format="PNG")

        result = compare_images(base, buf.getvalue(), with_thumbnail=False)
        original = DiffMetadata(cluster_summary=result.cluster_summary)
        dumped = original.model_dump(mode="json")
        roundtripped = DiffMetadata.model_validate(dumped)
        assert roundtripped == original
