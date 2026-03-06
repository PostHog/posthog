"""Tests for visual_review diff computation."""

import io

from PIL import Image

from products.visual_review.backend.diff import compute_diff


def _make_png(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    """Create a solid color PNG image."""
    img = Image.new("RGBA", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


class TestComputeDiff:
    def test_identical_images_zero_diff(self):
        red = (255, 0, 0, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, red)

        result = compute_diff(img1, img2)

        assert result.diff_percentage == 0.0
        assert result.diff_pixel_count == 0
        assert result.width == 10
        assert result.height == 10
        assert len(result.diff_hash) == 64  # BLAKE3 hex

    def test_completely_different_images_full_diff(self):
        red = (255, 0, 0, 255)
        blue = (0, 0, 255, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, blue)

        result = compute_diff(img1, img2)

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

        result = compute_diff(buf1.getvalue(), buf2.getvalue())

        assert result.diff_percentage == 50.0
        assert result.diff_pixel_count == 50

    def test_different_sizes_pads_to_larger(self):
        small = _make_png(5, 5, (255, 0, 0, 255))
        large = _make_png(10, 10, (255, 0, 0, 255))

        result = compute_diff(small, large)

        assert result.width == 10
        assert result.height == 10
        # 5x5 overlap is identical, padded area (75 pixels) differs
        assert result.diff_pixel_count == 75

    def test_threshold_controls_sensitivity(self):
        img1 = _make_png(10, 10, (100, 100, 100, 255))
        img2 = _make_png(10, 10, (105, 100, 100, 255))

        # Default threshold (0.1) tolerates small differences
        result = compute_diff(img1, img2)
        assert result.diff_pixel_count == 0

        # Zero threshold catches everything
        result = compute_diff(img1, img2, threshold=0.0)
        assert result.diff_pixel_count == 100

    def test_diff_image_is_valid_png(self):
        red = (255, 0, 0, 255)
        blue = (0, 0, 255, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, blue)

        result = compute_diff(img1, img2)

        diff_img = Image.open(io.BytesIO(result.diff_image))
        assert diff_img.size == (10, 10)
        assert diff_img.mode == "RGBA"
