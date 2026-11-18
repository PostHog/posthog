"""Tests for visual_review diff computation."""

import io

from PIL import Image

from products.visual_review.backend.diff import ALIGN_MAX_ROWS, compare_images
from products.visual_review.backend.tests.conftest import make_striped_png, to_png


def _make_png(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    """Create a solid color PNG image."""
    img = Image.new("RGBA", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _red_row_indices(image: Image.Image) -> set[int]:
    rows: set[int] = set()
    for y in range(image.height):
        for x in range(image.width):
            pixel = image.getpixel((x, y))
            if isinstance(pixel, tuple) and pixel[:3] == (255, 0, 0):
                rows.add(y)
                break
    return rows


class TestCompareImages:
    def test_identical_images_zero_diff(self):
        red = (255, 0, 0, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, red)

        result = compare_images(img1, img2)

        assert result.diff_percentage == 0.0
        assert result.diff_pixel_count == 0
        assert result.width == 10
        assert result.height == 10
        assert len(result.diff_hash) == 64  # BLAKE3 hex
        # No pixel differs, so there is nothing to align and no alignment runs.
        assert result.row_shift is None

    def test_completely_different_images_full_diff(self):
        red = (255, 0, 0, 255)
        blue = (0, 0, 255, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, blue)

        result = compare_images(img1, img2)

        assert result.diff_percentage == 100.0
        assert result.diff_pixel_count == 100

    def test_partial_diff(self):
        img1 = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        img2 = Image.new("RGBA", (10, 10), (255, 0, 0, 255))

        for x in range(5, 10):
            for y in range(10):
                img2.putpixel((x, y), (0, 0, 255, 255))

        buf1 = io.BytesIO()
        img1.save(buf1, format="PNG")
        buf2 = io.BytesIO()
        img2.save(buf2, format="PNG")

        result = compare_images(buf1.getvalue(), buf2.getvalue())

        assert result.diff_percentage == 50.0
        assert result.diff_pixel_count == 50

    def test_different_sizes_pads_to_larger(self):
        small = _make_png(5, 5, (255, 0, 0, 255))
        large = _make_png(10, 10, (255, 0, 0, 255))

        result = compare_images(small, large)

        assert result.width == 10
        assert result.height == 10
        # 5x5 overlap is identical, padded area (75 pixels) differs
        assert result.diff_pixel_count == 75

    def test_threshold_controls_sensitivity(self):
        img1 = _make_png(10, 10, (100, 100, 100, 255))
        img2 = _make_png(10, 10, (105, 100, 100, 255))

        # Default threshold (0.1) tolerates small differences
        result = compare_images(img1, img2)
        assert result.diff_pixel_count == 0

        # Zero threshold catches everything
        result = compare_images(img1, img2, threshold=0.0)
        assert result.diff_pixel_count == 100

    def test_diff_image_is_valid_png(self):
        red = (255, 0, 0, 255)
        blue = (0, 0, 255, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, blue)

        result = compare_images(img1, img2)

        assert result.diff_image is not None
        diff_img = Image.open(io.BytesIO(result.diff_image))
        assert diff_img.size == (10, 10)
        assert diff_img.mode in ("RGB", "RGBA")

    def test_inserted_row_diff_image_marks_only_that_row(self):
        # Each row has its own color, so row alignment has one answer and the
        # diff image can only be red where the new row landed. Without
        # alignment every row below the insert would come back red.
        baseline_rows = [(10 * i % 250, 40, 200, 255) for i in range(20)]
        current_rows = [*baseline_rows[:8], (255, 255, 255, 255), *baseline_rows[8:]]

        result = compare_images(make_striped_png(baseline_rows), make_striped_png(current_rows))

        assert result.row_shift is not None
        assert result.row_shift.inserted_rows == 1
        assert [(b.y, b.rows, b.kind) for b in result.row_shift.bands] == [(8, 1, "inserted")]

        assert result.diff_image is not None
        diff_img = Image.open(io.BytesIO(result.diff_image)).convert("RGBA")
        assert diff_img.size == (20, 21)  # the current image, one row taller than the baseline
        assert _red_row_indices(diff_img) == {8}

    def test_alignment_skipped_past_the_row_cap(self):
        rows = ALIGN_MAX_ROWS + 1
        baseline = _make_png(1, rows, (255, 255, 255, 255))
        current = Image.new("RGBA", (1, rows), (255, 255, 255, 255))
        current.putpixel((0, 0), (0, 0, 0, 255))

        result = compare_images(baseline, to_png(current))

        assert result.diff_pixel_count == 1
        assert result.row_shift is None
        assert result.aligned_diff_pixel_count == result.diff_pixel_count

    def test_deleted_row_result_dimensions_follow_the_diff_image(self):
        # The baseline is the taller of the two, so the padded buffers the
        # metrics run over are 20x20 while the aligned diff image is the
        # current image at 20x19. The result has to report the image's own
        # size, because it is what the diff artifact row records and what the
        # frontend scales its cluster and band overlays by.
        baseline_rows = [(10 * i % 250, 40, 200, 255) for i in range(20)]
        current_rows = [*baseline_rows[:8], *baseline_rows[9:]]

        result = compare_images(make_striped_png(baseline_rows), make_striped_png(current_rows))

        assert result.row_shift is not None
        assert [(b.y, b.rows, b.kind) for b in result.row_shift.bands] == [(8, 1, "deleted")]

        assert result.diff_image is not None
        diff_img = Image.open(io.BytesIO(result.diff_image))
        assert (result.width, result.height) == diff_img.size == (20, 19)
