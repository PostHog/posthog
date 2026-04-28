"""Tests for two-tier diff classification (pixelmatch + SSIM)."""

import io

import numpy as np
from PIL import Image, ImageDraw

from products.visual_review.backend.diff import compute_diff
from products.visual_review.backend.diffing import PIXEL_DIFF_THRESHOLD_PERCENT, SSIM_DISSIMILARITY_THRESHOLD
from products.visual_review.backend.ssim import compute_ssim


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


def _classify(baseline_bytes: bytes, current_bytes: bytes) -> str:
    """Run the same two-tier classification logic as _diff_snapshot."""
    result = compute_diff(baseline_bytes, current_bytes)

    if result.diff_percentage >= PIXEL_DIFF_THRESHOLD_PERCENT:
        return "changed_by_pixelmatch"

    ssim_score = compute_ssim(baseline_bytes, current_bytes)
    ssim_dissimilarity = 1.0 - ssim_score

    if ssim_dissimilarity >= SSIM_DISSIMILARITY_THRESHOLD:
        return "changed_by_ssim"

    return "unchanged"


class TestComputeSSIM:
    def test_identical_images_score_one(self):
        img = _make_png(100, 100, (200, 100, 50, 255))
        assert compute_ssim(img, img) > 0.999

    def test_completely_different_images_low_score(self):
        img1 = _make_png(100, 100, (255, 0, 0, 255))
        img2 = _make_png(100, 100, (0, 0, 255, 255))
        assert compute_ssim(img1, img2) < 0.8

    def test_slight_difference_high_score(self):
        img1 = _make_png(100, 100, (100, 100, 100, 255))
        img2 = _make_png(100, 100, (105, 100, 100, 255))
        assert compute_ssim(img1, img2) > 0.99

    def test_small_images_below_window_size(self):
        img1 = _make_png(5, 5, (255, 0, 0, 255))
        img2 = _make_png(5, 5, (255, 0, 0, 255))
        assert compute_ssim(img1, img2) > 0.999

    def test_different_sizes_pads_to_larger(self):
        small = _make_png(50, 50, (200, 200, 200, 255))
        large = _make_png(100, 100, (200, 200, 200, 255))
        score = compute_ssim(small, large)
        # 75% of padded area is black vs gray — significant structural difference
        assert 0.0 < score < 1.0


class TestTwoTierClassification:
    """Tests for the combined pixelmatch + SSIM classification.

    The two-tier approach addresses tall-page dilution: a real UI change
    at the bottom of a long screenshot affects few pixels (below
    pixelmatch's 1% threshold) but produces a measurable structural
    shift that SSIM catches.
    """

    def test_obvious_change_caught_by_pixelmatch(self):
        red = _make_png(100, 100, (255, 0, 0, 255))
        blue = _make_png(100, 100, (0, 0, 255, 255))
        assert _classify(red, blue) == "changed_by_pixelmatch"

    def test_tall_page_change_caught_by_ssim(self):
        baseline = _make_tall_settings_page(extra_element=False)
        current = _make_tall_settings_page(extra_element=True)

        result = compute_diff(baseline, current)
        assert result.diff_percentage < PIXEL_DIFF_THRESHOLD_PERCENT

        ssim_dissimilarity = 1.0 - compute_ssim(baseline, current)
        assert ssim_dissimilarity > SSIM_DISSIMILARITY_THRESHOLD

        assert _classify(baseline, current) == "changed_by_ssim"

    def test_identical_images_classified_unchanged(self):
        page = _make_tall_settings_page(extra_element=False)
        assert _classify(page, page) == "unchanged"

    def test_subtle_noise_classified_unchanged(self):
        img1 = _make_png(100, 100, (100, 100, 100, 255))
        img2 = _make_png(100, 100, (105, 100, 100, 255))
        assert _classify(img1, img2) == "unchanged"
