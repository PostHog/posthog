import io
import zlib
import base64
import struct

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from parameterized import parameterized
from PIL import Image

from products.mcp_analytics.backend.custom_harness_icons import validate_harness_icon


def _logo(size: tuple[int, int] = (16, 16), color: tuple[int, int, int] = (200, 40, 40)) -> Image.Image:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((*color, 255), (size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4))
    return image


def _encode(mime: str, image: Image.Image, pil_format: str, **save_args: object) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format=pil_format, **save_args)
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}"


def _image_data_uri(mime: str, pil_format: str, size: tuple[int, int] = (16, 16)) -> str:
    return _encode(mime, _logo(size), pil_format)


def _two_frame_data_uri(mime: str, pil_format: str) -> str:
    return _encode(mime, _logo(), pil_format, save_all=True, append_images=[_logo(color=(40, 40, 200))])


def _almost_opaque_png_data_uri() -> str:
    image = Image.new("RGBA", (16, 16), (200, 40, 40, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    return _encode("image/png", image, "PNG")


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
            ("gif", _image_data_uri("image/gif", "GIF")),
            ("webp", _image_data_uri("image/webp", "WEBP")),
        ]
    )
    def test_accepts(self, _name: str, value: str) -> None:
        validate_harness_icon(value)

    @parameterized.expand(
        [
            ("jpeg_has_no_transparency", _encode("image/jpeg", Image.new("RGB", (16, 16)), "JPEG")),
            ("png_without_alpha", _encode("image/png", Image.new("RGB", (16, 16), (200, 40, 40)), "PNG")),
            ("png_with_an_opaque_background", _encode("image/png", Image.new("RGBA", (16, 16), "white"), "PNG")),
            ("png_with_almost_no_transparent_pixels", _almost_opaque_png_data_uri()),
            ("svg_can_carry_script", "data:image/svg+xml;base64," + base64.b64encode(b"<svg></svg>").decode()),
            ("not_a_data_uri", "https://example.com/icon.png"),
            ("not_base64", "data:image/png;base64,not base64!"),
            ("trailing_newline", _image_data_uri("image/png", "PNG") + "\n"),
            ("not_a_png", "data:image/png;base64," + base64.b64encode(b"hello").decode()),
            ("type_does_not_match_content", _image_data_uri("image/png", "GIF")),
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
