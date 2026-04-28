"""Unit tests for hashing — pixel pipeline determinism and DoS guards."""

import io

import pytest

from PIL import Image

from products.visual_review.backend.hashing import ImageTooLargeError, hash_image


def _png_bytes(color: tuple[int, int, int, int], size: tuple[int, int] = (4, 4)) -> bytes:
    img = Image.new("RGBA", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestHashImage:
    def test_deterministic_for_same_pixels(self):
        png = _png_bytes((255, 0, 0, 255))
        assert hash_image(png) == hash_image(png)

    def test_different_pixels_produce_different_hashes(self):
        assert hash_image(_png_bytes((255, 0, 0, 255))) != hash_image(_png_bytes((0, 255, 0, 255)))

    def test_rgb_without_alpha_promoted_to_opaque_rgba(self):
        # PNG saved as RGB should hash the same as the equivalent RGBA-with-255-alpha.
        rgb = Image.new("RGB", (4, 4), (10, 20, 30))
        buf = io.BytesIO()
        rgb.save(buf, format="PNG")

        assert hash_image(buf.getvalue()) == hash_image(_png_bytes((10, 20, 30, 255)))

    def test_rejects_payload_over_byte_limit(self):
        with pytest.raises(ImageTooLargeError):
            hash_image(b"\x89PNG" + b"\x00" * (65 * 1024 * 1024))
