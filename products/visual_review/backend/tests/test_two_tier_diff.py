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
from products.visual_review.backend.tests.conftest import insert_background_rows, make_striped_png, open_png, to_png


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


PAGE_BACKGROUND = (245, 245, 245, 255)


def _insert_rows(png_bytes: bytes, y: int, rows: int) -> bytes:
    return insert_background_rows(png_bytes, y, rows, PAGE_BACKGROUND)


def _grow_rows(png_bytes: bytes, y: int, rows: int) -> bytes:
    # A panel that grows repeats its edge row, so the new rows match the row above them.
    image = open_png(png_bytes)
    width, height = image.size
    out = Image.new("RGBA", (width, height + rows))
    out.paste(image.crop((0, 0, width, y)), (0, 0))
    for i in range(rows):
        out.paste(image.crop((0, y - 1, width, y)), (0, y + i))
    out.paste(image.crop((0, y, width, height)), (0, y + rows))
    return to_png(out)


def _classify(baseline_bytes: bytes, current_bytes: bytes) -> ChangeKind | None:
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
    # A panel that grows by a pixel moves everything below it down, which a
    # top-aligned pixel diff reads as a page-wide change. Row alignment pairs
    # the rows that exist in both images so the diff describes what changed.

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
        current = _insert_rows(baseline, y=200, rows=inserted_rows)

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

    @pytest.mark.parametrize(
        "page_height, moved_rows, expected_kind",
        [
            pytest.param(3000, SHIFT_ABSORB_MAX_ROWS, None, id="cap_still_absorbed"),
            pytest.param(3000, SHIFT_ABSORB_MAX_ROWS + 1, ChangeKind.LAYOUT, id="past_cap_is_layout"),
            # On a short page the doubled band area alone would cross the pixel threshold.
            pytest.param(100, SHIFT_ABSORB_MAX_ROWS, None, id="cap_on_a_short_page"),
        ],
    )
    def test_same_height_translation_counts_the_movement_once(
        self, page_height: int, moved_rows: int, expected_kind: ChangeKind | None
    ):
        # A page that keeps its height while its content moves down shows up
        # as the same number of inserted and deleted rows. Summing both sides
        # would double the movement and push a cap-sized shift into layout.
        baseline = _make_tall_settings_page(height=page_height)
        grown = open_png(_grow_rows(baseline, y=page_height // 2, rows=moved_rows))
        current = to_png(grown.crop((0, 0, grown.width, grown.height - moved_rows)))

        result = compare_images(baseline, current, with_thumbnail=False)
        assert result.row_shift is not None
        assert (result.row_shift.inserted_rows, result.row_shift.deleted_rows) == (moved_rows, moved_rows)
        assert result.row_shift.shifted_rows == moved_rows

        assert classify_compare_result(result) == expected_kind

    @pytest.mark.parametrize(
        "page_rows, expected_kind",
        [
            pytest.param(20, ChangeKind.PIXEL, id="bar_across_a_small_component"),
            pytest.param(3000, None, id="two_rows_on_a_tall_page"),
        ],
    )
    def test_inserted_rows_count_their_own_area(self, page_rows: int, expected_kind: ChangeKind | None):
        # The residual never sees rows that have no counterpart, so the cap
        # alone would absorb two black rows across a twenty-row component.
        # The band's own area has to count against the pixel threshold.
        colors = [(200 + (i * 7) % 50, 200 + (i * 13) % 50, 220, 255) for i in range(page_rows)]
        baseline = make_striped_png(colors, width=100)
        current = insert_background_rows(baseline, y=page_rows // 2, rows=2, fill=(0, 0, 0, 255))

        result = compare_images(baseline, current, with_thumbnail=False)
        assert result.row_shift is not None
        assert result.row_shift.shifted_rows == 2
        assert result.row_shift.residual_percentage == 0

        assert classify_compare_result(result) == expected_kind

    def test_over_cap_shift_is_layout_even_when_its_band_covers_the_page(self):
        # The band's area counts as changed pixels, and a big move on a short
        # page covers more of it than the pixel threshold. The move is still
        # the change, so it has to read as layout, not as a pixel diff.
        baseline = _make_tall_settings_page(height=200)
        current = _insert_rows(baseline, y=80, rows=40)

        result = compare_images(baseline, current, with_thumbnail=False)
        assert result.row_shift is not None
        assert result.aligned_diff_percentage > PIXEL_DIFF_THRESHOLD_PERCENT

        assert classify_compare_result(result) == ChangeKind.LAYOUT

    @pytest.mark.parametrize("destination", [pytest.param(800, id="interior"), pytest.param(3000, id="bottom_edge")])
    def test_relocated_thin_element_is_layout_not_a_small_shift(self, destination: int):
        # A one-row line that moved from y=100 elsewhere aligns as one delete
        # plus one insert with no residual. Counting rows alone calls that a
        # one-row shift; the inserted row's pixels equal the deleted row's,
        # which says the line moved. The bottom edge is the case that looks
        # exactly like a page translation from the band positions alone.
        colors = [(200 + (i * 7) % 50, 200 + (i * 13) % 50, 220, 255) for i in range(3000)]
        line = (0, 0, 0, 255)
        baseline = make_striped_png([*colors[:100], line, *colors[100:]], width=100)
        current = make_striped_png([*colors[:destination], line, *colors[destination:]], width=100)

        result = compare_images(baseline, current, with_thumbnail=False)
        assert result.row_shift is not None
        assert (result.row_shift.inserted_rows, result.row_shift.deleted_rows) == (1, 1)
        assert result.row_shift.relocated_rows == 1

        assert classify_compare_result(result) == ChangeKind.LAYOUT

    def test_page_shift_that_exposes_matching_edge_padding_still_absorbs(self):
        # A fixed-height page that moved down by a row exposes a padding row
        # at the top and crops one at the bottom. Both are padding, so they
        # match, and the top one differs from the content below it. That is
        # not an element that moved: neither row stood out in the interior.
        padding = (245, 245, 245, 255)
        colors = [(200 + (i * 7) % 50, 200 + (i * 13) % 50, 220, 255) for i in range(300)]
        baseline = make_striped_png([padding, *colors, padding], width=100)
        current = make_striped_png([padding, padding, *colors], width=100)

        result = compare_images(baseline, current, with_thumbnail=False)
        assert result.row_shift is not None
        assert (result.row_shift.inserted_rows, result.row_shift.deleted_rows) == (1, 1)
        assert result.row_shift.relocated_rows == 0

        assert classify_compare_result(result) is None

    def test_shift_too_big_to_check_for_relocation_goes_to_review(self, mocker):
        # The relocation check decodes the images again. Past the pixel bound
        # it is skipped, and a shift with both inserts and deletes must then
        # reach a reviewer rather than absorb on the strength of a guess.
        mocker.patch("products.visual_review.backend.diff.RELOCATION_CHECK_MAX_PIXELS", 1)
        baseline = _make_tall_settings_page()
        grown = open_png(_grow_rows(baseline, y=1500, rows=1))
        current = to_png(grown.crop((0, 0, grown.width, grown.height - 1)))

        result = compare_images(baseline, current, with_thumbnail=False)
        assert result.row_shift is not None
        assert result.row_shift.relocated_rows == 1

        assert classify_compare_result(result) == ChangeKind.LAYOUT

    def test_shift_plus_real_change_is_not_absorbed(self):
        baseline = _make_tall_settings_page()
        shifted = open_png(_insert_rows(baseline, y=200, rows=1))
        ImageDraw.Draw(shifted).rectangle([(20, 1000), (380, 1060)], fill=(255, 0, 0, 255))

        result = compare_images(baseline, to_png(shifted), with_thumbnail=False)

        assert result.row_shift is not None
        assert result.row_shift.inserted_rows == 1
        assert classify_compare_result(result) in (ChangeKind.PIXEL, ChangeKind.STRUCTURAL)

    def test_partial_width_drift_is_not_absorbed(self):
        # Only the right half of a block moves down a row. That is not a page
        # shift, so it must not ride the absorb path out of review.
        baseline = _make_tall_settings_page()
        drifted = open_png(baseline)
        width, _ = drifted.size
        half = drifted.crop((width // 2, 500, width, 900))
        drifted.paste((245, 245, 245, 255), (width // 2, 500, width, 900))
        drifted.paste(half, (width // 2, 501))

        assert _classify(baseline, to_png(drifted)) is not None
