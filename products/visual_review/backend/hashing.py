"""
Canonical image hashing for upload integrity verification.

Matches the CLI's hashing pipeline: PNG → sRGB RGBA → BLAKE3.
This ensures the server can verify that uploaded bytes correspond
to the content hash the CLI claimed.
"""

import io

from blake3 import blake3
from PIL import Image, ImageCms

# Cap decoded pixel count to bound memory. A 7000×7000 RGBA image is ~196 MB —
# plenty for screenshots, well under Pillow's default DecompressionBombWarning.
# Pillow raises DecompressionBombError above this (instead of just warning).
_MAX_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = _MAX_PIXELS

# Reject the PNG before decode if it's larger than this. Compressed PNGs above
# 64 MiB are almost certainly bogus for a screenshot upload.
_MAX_PNG_BYTES = 64 * 1024 * 1024

_SRGB_PROFILE = ImageCms.createProfile("sRGB")


class ImageTooLargeError(Exception):
    """Uploaded image exceeds the size limit allowed for hashing."""


def _to_srgb_rgba(img: Image.Image) -> Image.Image:
    """Convert an image's pixels to sRGB and ensure RGBA layout.

    Mirrors the CLI's `sharp(...).toColorspace('srgb').ensureAlpha().raw()`:
    if the PNG carries a non-sRGB ICC profile (Display P3 macOS screenshots,
    Adobe RGB, etc.), pixels are transformed into sRGB so byte-level hashes
    match across CLI and server.
    """
    icc = img.info.get("icc_profile")
    if icc:
        try:
            src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            # Intermediate RGB conversion (ImageCms can't target RGBA directly);
            # alpha is preserved separately below.
            alpha = img.split()[-1] if img.mode in ("RGBA", "LA", "PA") else None
            rgb = img.convert("RGB") if img.mode != "RGB" else img
            rgb = ImageCms.profileToProfile(rgb, src_profile, _SRGB_PROFILE, outputMode="RGB")
            if alpha is None:
                return rgb.convert("RGBA")
            rgba = rgb.convert("RGBA")
            rgba.putalpha(alpha)
            return rgba
        except ImageCms.PyCMSError:
            # Malformed ICC profile — fall through to plain RGBA conversion.
            # Hash mismatch is preferable to a server crash on a bad profile.
            pass
    return img.convert("RGBA")


def hash_image(png_bytes: bytes) -> str:
    """Decode PNG to sRGB RGBA pixels and return the BLAKE3 hex digest."""
    if len(png_bytes) > _MAX_PNG_BYTES:
        raise ImageTooLargeError(f"PNG is {len(png_bytes)} bytes, exceeds {_MAX_PNG_BYTES} limit")
    img = Image.open(io.BytesIO(png_bytes))
    img.load()
    rgba = _to_srgb_rgba(img)
    return blake3(rgba.tobytes()).hexdigest()
