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
        # Two identical red images
        red = (255, 0, 0, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, red)

        result = compute_diff(img1, img2)

        assert result.diff_percentage == 0.0
        assert result.diff_pixel_count == 0
        assert result.width == 10
        assert result.height == 10
        assert len(result.diff_hash) == 64  # SHA256 hex

    def test_completely_different_images_full_diff(self):
        # Red vs Blue - completely different
        red = (255, 0, 0, 255)
        blue = (0, 0, 255, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, blue)

        result = compute_diff(img1, img2)

        assert result.diff_percentage == 100.0
        assert result.diff_pixel_count == 100  # 10x10 = 100 pixels
        assert result.width == 10
        assert result.height == 10

    def test_partial_diff(self):
        # Create two images with different halves
        img1 = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        img2 = Image.new("RGBA", (10, 10), (255, 0, 0, 255))

        # Change right half of img2 to blue
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
        # 5x5 vs 10x10 - smaller image gets padded
        small = _make_png(5, 5, (255, 0, 0, 255))
        large = _make_png(10, 10, (255, 0, 0, 255))

        result = compute_diff(small, large)

        # Result should be 10x10
        assert result.width == 10
        assert result.height == 10
        # The 5x5 overlap is identical, but the padded area differs
        # Padded area = 100 - 25 = 75 pixels differ
        assert result.diff_pixel_count == 75

    def test_threshold_ignores_small_differences(self):
        # Two nearly identical images (off by 5 in red channel)
        img1 = _make_png(10, 10, (100, 100, 100, 255))
        img2 = _make_png(10, 10, (105, 100, 100, 255))

        # With default threshold of 10, these should be identical
        result = compute_diff(img1, img2, threshold=10)
        assert result.diff_pixel_count == 0

        # With threshold of 0, all pixels differ
        result = compute_diff(img1, img2, threshold=0)
        assert result.diff_pixel_count == 100

    def test_diff_image_is_valid_png(self):
        red = (255, 0, 0, 255)
        blue = (0, 0, 255, 255)
        img1 = _make_png(10, 10, red)
        img2 = _make_png(10, 10, blue)

        result = compute_diff(img1, img2)

        # Verify diff_image is a valid PNG
        diff_img = Image.open(io.BytesIO(result.diff_image))
        assert diff_img.size == (10, 10)
        assert diff_img.mode == "RGBA"
