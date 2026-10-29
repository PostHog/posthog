import io
import zlib
import base64
import struct

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from parameterized import parameterized
from PIL import Image

from products.mcp_analytics.backend.custom_harness_icons import validate_harness_icon


def _image_data_uri(mime: str, pil_format: str, size: tuple[int, int] = (16, 16)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(buffer, format=pil_format)
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}"


def _two_frame_data_uri(mime: str, pil_format: str) -> str:
    buffer = io.BytesIO()
    first, second = Image.new("RGB", (16, 16), (200, 40, 40)), Image.new("RGB", (16, 16), (40, 40, 200))
    first.save(buffer, format=pil_format, save_all=True, append_images=[second])
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _handmade_png_data_uri(width: int, height: int, pixel_data: bytes, extra: bytes = b"") -> str:
    """A PNG with valid chunk checksums whose header and pixels can say anything."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + extra
        + _png_chunk(b"IDAT", pixel_data)
        + _png_chunk(b"IEND", b"")
    )
    return f"data:image/png;base64,{base64.b64encode(png).decode()}"


class TestValidateHarnessIcon(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_means_no_icon", ""),
            ("png", _image_data_uri("image/png", "PNG")),
            ("jpeg", _image_data_uri("image/jpeg", "JPEG")),
            ("gif", _image_data_uri("image/gif", "GIF")),
            ("webp", _image_data_uri("image/webp", "WEBP")),
            ("multi_picture_jpeg_from_a_phone", _two_frame_data_uri("image/jpeg", "MPO")),
        ]
    )
    def test_accepts(self, _name: str, value: str) -> None:
        validate_harness_icon(value)

    @parameterized.expand(
        [
            ("svg_can_carry_script", "data:image/svg+xml;base64," + base64.b64encode(b"<svg></svg>").decode()),
            ("not_a_data_uri", "https://example.com/icon.png"),
            ("not_base64", "data:image/png;base64,not base64!"),
            ("trailing_newline", _image_data_uri("image/png", "PNG") + "\n"),
            ("not_an_image", "data:image/png;base64," + base64.b64encode(b"hello").decode()),
            ("type_does_not_match_content", _image_data_uri("image/png", "JPEG")),
            ("too_wide", _image_data_uri("image/png", "PNG", size=(300, 10))),
            ("decompression_bomb", _handmade_png_data_uri(20_000, 20_000, zlib.compress(b""))),
            ("pixels_do_not_decode", _handmade_png_data_uri(16, 16, b"not zlib data")),
            ("animated_gif", _two_frame_data_uri("image/gif", "GIF")),
            ("animated_webp", _two_frame_data_uri("image/webp", "WEBP")),
            ("bmp_declared_as_png", _image_data_uri("image/png", "BMP")),
            (
                "gif_frame_outside_the_screen",
                "data:image/gif;base64,"
                "R0lGODdhEAAQAFcAAAECAwAAAAAsAAAAACwAAAAAEAAQxUAIHQCUCBxIsKDBgwgTKlzIsKHDixAjSpxIsaLFrAEBADs=",
            ),
            (
                "text_chunk_too_large_to_expand",
                _handmade_png_data_uri(
                    16,
                    16,
                    zlib.compress(b"\x00" * 16 * 49),
                    extra=_png_chunk(b"zTXt", b"k\x00\x00" + zlib.compress(b"a" * 2_000_000)),
                ),
            ),
            ("too_many_bytes", "data:image/png;base64," + base64.b64encode(b"\x00" * 20_000).decode()),
        ]
    )
    def test_rejects(self, _name: str, value: str) -> None:
        with self.assertRaises(ValidationError):
            validate_harness_icon(value)
