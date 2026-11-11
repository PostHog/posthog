import io
import re
import base64
import binascii

from django.core.exceptions import ValidationError

from PIL import Image, UnidentifiedImageError

MAX_HARNESS_ICON_BYTES = 16 * 1024
MAX_HARNESS_ICON_SIDE_PX = 256
# The icon shows as a one-color mask, so without transparent pixels it is a plain square.
MIN_TRANSPARENT_PIXEL_SHARE = 0.1

# SVG is left out on purpose: it can carry script, and only a raster image can be decoded and checked here.
# Pillow opens only these formats, so no other decoder ever runs on the uploaded bytes.
_PIL_FORMATS_BY_SUBTYPE = {"png": ["PNG"], "gif": ["GIF"], "webp": ["WEBP"]}
_DATA_URI = re.compile(r"data:image/(png|gif|webp);base64,([A-Za-z0-9+/]+={0,2})")
# Base64 needs 4 characters for every 3 bytes, plus the short prefix.
_MAX_DATA_URI_LENGTH = MAX_HARNESS_ICON_BYTES * 4 // 3 + 64


def validate_harness_icon(value: str) -> None:
    """Raise unless `value` is empty or a small base64 PNG, GIF or WebP data URI with a transparent background."""
    if value == "":
        return
    if len(value) > _MAX_DATA_URI_LENGTH:
        raise ValidationError(f"The icon must be {MAX_HARNESS_ICON_BYTES // 1024} KB or smaller.")

    match = _DATA_URI.fullmatch(value)
    if match is None:
        raise ValidationError("Paste a PNG, GIF or WebP image as a base64 data URI.")
    subtype, encoded = match.groups()

    try:
        raw = base64.b64decode(encoded, validate=True)
    except binascii.Error:
        raise ValidationError("The icon is not valid base64.")
    if len(raw) > MAX_HARNESS_ICON_BYTES:
        raise ValidationError(f"The icon must be {MAX_HARNESS_ICON_BYTES // 1024} KB or smaller.")

    formats = _PIL_FORMATS_BY_SUBTYPE[subtype]
    try:
        with Image.open(io.BytesIO(raw), formats=formats) as image:
            width, height = image.size
            if max(width, height) > MAX_HARNESS_ICON_SIDE_PX:
                raise ValidationError(
                    f"The icon must be {MAX_HARNESS_ICON_SIDE_PX} by {MAX_HARNESS_ICON_SIDE_PX} pixels or smaller."
                )
            # Only the first frame is checked and decoded, so a later frame could be any size.
            if getattr(image, "is_animated", False):
                raise ValidationError("The icon must be a still image, not an animation.")
            image.verify()
        # verify() checks structure only and leaves the image unusable, so decode the pixels from a fresh open.
        with Image.open(io.BytesIO(raw), formats=formats) as image:
            image.load()
            transparent_pixels = image.convert("RGBA").getchannel("A").histogram()[0]
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ValidationError(f"The icon is not a valid image/{subtype} image.")
    if transparent_pixels < width * height * MIN_TRANSPARENT_PIXEL_SHARE:
        raise ValidationError(
            "The icon needs a transparent background. Save the logo as a PNG, GIF or WebP with transparency around it."
        )
