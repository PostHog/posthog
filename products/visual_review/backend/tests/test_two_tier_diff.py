"""Tests for two-tier diff classification (pixelmatch + SSIM)."""

import io

import pytest

import numpy as np
from PIL import Image, ImageDraw

from products.visual_review.backend.diff import compare_images
from products.visual_review.backend.diffing import classify_compare_result
from products.visual_review.backend.facade.contracts import (
    PIXEL_DIFF_THRESHOLD_PERCENT,
    SHIFT_ABSORB_MAX_ROWS,
    SSIM_DISSIMILARITY_THRESHOLD,
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


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _open(png_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def _insert_background_rows(png_bytes: bytes, y: int, rows: int) -> bytes:
    """Push everything below `y` down by `rows` rows of page background.

    The image grows by `rows`, which is what a panel that gained a pixel of
    padding does to a full-page screenshot.
    """
    img = _open(png_bytes)
    width, height = img.size
    out = Image.new("RGBA", (width, height + rows), (245, 245, 245, 255))
    out.paste(img.crop((0, 0, width, y)), (0, 0))
    out.paste(img.crop((0, y, width, height)), (0, y + rows))
    return _to_png(out)


def _insert_bordered_block(png_bytes: bytes, y: int, rows: int) -> bytes:
    """Insert a block of new content at `y` and push everything below it down."""
    img = _open(png_bytes)
    width, height = img.size
    out = Image.new("RGBA", (width, height + rows), (245, 245, 245, 255))
    out.paste(img.crop((0, 0, width, y)), (0, 0))
    ImageDraw.Draw(out).rectangle(
        [(20, y), (width - 20, y + rows - 1)], fill=(255, 243, 224, 255), outline=(200, 160, 100, 255)
    )
    out.paste(img.crop((0, y, width, height)), (0, y + rows))
    return _to_png(out)


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


class TestRowShiftClassification:
    """Tests for absorbing a vertical shift instead of flagging the whole page.

    A panel that grows by a pixel moves everything below it down, which a
    top-aligned pixel diff reads as a page-wide change. Row alignment pairs
    the rows that exist in both images so the diff describes what actually
    changed.
    """

    @pytest.mark.parametrize(
        "inserted_rows, expected_kind",
        [
            pytest.param(1, None, id="one_row_absorbed"),
            pytest.param(SHIFT_ABSORB_MAX_ROWS, None, id="cap_still_absorbed"),
            pytest.param(SHIFT_ABSORB_MAX_ROWS + 1, ChangeKind.LAYOUT, id="past_cap_is_layout"),
        ],
    )
    def test_background_row_insert_ladder(self, inserted_rows: int, expected_kind: ChangeKind | None):
        baseline = _make_tall_settings_page()
        current = _insert_background_rows(baseline, y=200, rows=inserted_rows)

        result = compare_images(baseline, current, with_thumbnail=False)
        assert result.row_shift is not None
        assert result.row_shift.inserted_rows == inserted_rows
        assert result.row_shift.deleted_rows == 0
        # Everything below the seam is identical once the rows are paired.
        assert result.row_shift.residual_percentage < 0.01
        # Without alignment the same pair reads as a large pixel diff.
        assert result.diff_percentage > PIXEL_DIFF_THRESHOLD_PERCENT
        assert result.row_shift.raw_diff_percentage == result.diff_percentage

        bands = result.row_shift.bands
        assert len(bands) == 1
        assert (bands[0].rows, bands[0].kind) == (inserted_rows, "inserted")
        # The rows around y=200 are page background, and the aligner is free to
        # put the seam anywhere inside that identical run, so the band lands
        # near the insert rather than exactly on it.
        assert 200 <= bands[0].y <= 215

        assert classify_compare_result(result) == expected_kind

    def test_inserted_block_counts_its_own_pixels(self):
        # The residual only covers rows present in both images, so an inserted
        # block would otherwise cost nothing. Charging it a full row of pixels
        # keeps a real block of new content visible in the stored percentage.
        baseline = _make_tall_settings_page()
        current = _insert_bordered_block(baseline, y=200, rows=40)

        result = compare_images(baseline, current, with_thumbnail=False)

        assert result.row_shift is not None
        assert result.row_shift.inserted_rows == 40
        assert result.aligned_diff_percentage > result.row_shift.residual_percentage
        assert classify_compare_result(result) == ChangeKind.LAYOUT

    def test_shift_plus_real_change_is_not_absorbed(self):
        baseline = _make_tall_settings_page()
        shifted = _open(_insert_background_rows(baseline, y=200, rows=1))
        ImageDraw.Draw(shifted).rectangle([(20, 1000), (380, 1060)], fill=(255, 0, 0, 255))

        result = compare_images(baseline, _to_png(shifted), with_thumbnail=False)

        assert result.row_shift is not None
        assert result.row_shift.inserted_rows == 1
        assert classify_compare_result(result) in (ChangeKind.PIXEL, ChangeKind.STRUCTURAL)

    def test_partial_width_drift_is_not_absorbed(self):
        # Only the right half of a block moves down a row. That is not a page
        # shift, so it must not ride the absorb path out of review.
        baseline = _make_tall_settings_page()
        drifted = _open(baseline)
        width, _ = drifted.size
        half = drifted.crop((width // 2, 500, width, 900))
        drifted.paste((245, 245, 245, 255), (width // 2, 500, width, 900))
        drifted.paste(half, (width // 2, 501))

        assert _classify(baseline, _to_png(drifted)) is not None
