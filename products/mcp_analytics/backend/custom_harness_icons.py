import io
import re
import base64
import binascii

from django.core.exceptions import ValidationError

from PIL import Image, UnidentifiedImageError

MAX_HARNESS_ICON_BYTES = 16 * 1024
MAX_HARNESS_ICON_SIDE_PX = 256

# SVG is left out on purpose: it can carry script, and only a raster image can be decoded and checked here.
_PIL_FORMAT_BY_SUBTYPE = {"png": "PNG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP"}
_DATA_URI = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/]+={0,2})$")
# Base64 needs 4 characters for every 3 bytes, plus the short prefix.
_MAX_DATA_URI_LENGTH = MAX_HARNESS_ICON_BYTES * 4 // 3 + 64


def validate_harness_icon(value: str) -> None:
    """Raise unless `value` is empty or a small base64 PNG, JPEG, GIF or WebP data URI whose bytes match its type."""
    if value == "":
        return
    if len(value) > _MAX_DATA_URI_LENGTH:
        raise ValidationError(f"The icon must be {MAX_HARNESS_ICON_BYTES // 1024} KB or smaller.")

    match = _DATA_URI.match(value)
    if match is None:
        raise ValidationError("Paste a PNG, JPEG, GIF or WebP image as a base64 data URI.")
    subtype, encoded = match.groups()

    try:
        raw = base64.b64decode(encoded, validate=True)
    except binascii.Error:
        raise ValidationError("The icon is not valid base64.")
    if len(raw) > MAX_HARNESS_ICON_BYTES:
        raise ValidationError(f"The icon must be {MAX_HARNESS_ICON_BYTES // 1024} KB or smaller.")

    try:
        with Image.open(io.BytesIO(raw)) as image:
            pil_format, (width, height) = image.format, image.size
            if max(width, height) > MAX_HARNESS_ICON_SIDE_PX:
                raise ValidationError(
                    f"The icon must be {MAX_HARNESS_ICON_SIDE_PX} by {MAX_HARNESS_ICON_SIDE_PX} pixels or smaller."
                )
            image.verify()
        # verify() checks structure only and leaves the image unusable, so decode the pixels from a fresh open.
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValidationError("The icon is not a valid image.")

    if pil_format != _PIL_FORMAT_BY_SUBTYPE[subtype]:
        raise ValidationError(f"The icon says it is image/{subtype}, but its content is a different image type.")
