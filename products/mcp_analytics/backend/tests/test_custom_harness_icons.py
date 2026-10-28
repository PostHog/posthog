import io
import base64

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from parameterized import parameterized
from PIL import Image

from products.mcp_analytics.backend.custom_harness_icons import validate_harness_icon


def _image_data_uri(mime: str, pil_format: str, size: tuple[int, int] = (16, 16)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(buffer, format=pil_format)
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}"


class TestValidateHarnessIcon(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_means_no_icon", ""),
            ("png", _image_data_uri("image/png", "PNG")),
            ("jpeg", _image_data_uri("image/jpeg", "JPEG")),
            ("gif", _image_data_uri("image/gif", "GIF")),
            ("webp", _image_data_uri("image/webp", "WEBP")),
        ]
    )
    def test_accepts(self, _name: str, value: str) -> None:
        validate_harness_icon(value)

    @parameterized.expand(
        [
            ("svg_can_carry_script", "data:image/svg+xml;base64," + base64.b64encode(b"<svg></svg>").decode()),
            ("not_a_data_uri", "https://example.com/icon.png"),
            ("not_base64", "data:image/png;base64,not base64!"),
            ("not_an_image", "data:image/png;base64," + base64.b64encode(b"hello").decode()),
            ("type_does_not_match_content", _image_data_uri("image/png", "JPEG")),
            ("too_wide", _image_data_uri("image/png", "PNG", size=(300, 10))),
            ("too_many_bytes", "data:image/png;base64," + base64.b64encode(b"\x00" * 20_000).decode()),
        ]
    )
    def test_rejects(self, _name: str, value: str) -> None:
        with self.assertRaises(ValidationError):
            validate_harness_icon(value)
