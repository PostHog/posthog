"""
Canonical image hashing for upload integrity verification.

Mirrors the CLI's pipeline (PNG → RGBA pixel buffer → BLAKE3) closely enough
to verify upload integrity. The CLI uses sharp's
``toColorspace('srgb').ensureAlpha().raw()``; for inputs without an embedded
ICC profile (the case for every screenshot Playwright/Storybook produce in
CI), Pillow's ``convert("RGBA")`` produces byte-identical pixel buffers.

Known limitation: PNGs with an embedded non-sRGB ICC profile (e.g. Display P3
macOS screenshots) hash differently between sharp's libvips engine and any
Pillow pipeline. Both engines transform but disagree at the byte level. We
accept this — those uploads will fail integrity verification with a clear
error rather than silently approve mismatched bytes. If real-world uploads
start carrying ICC profiles, the fix is to align both ends on a profile-strip
pipeline rather than chase engine parity.
"""

import io

from blake3 import blake3
from PIL import Image

# Cap decoded pixel count to bound memory. A 7000×7000 RGBA image is ~196 MB —
# plenty for screenshots, well under Pillow's default DecompressionBombWarning.
# Pillow raises DecompressionBombError above this (instead of just warning).
_MAX_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = _MAX_PIXELS

# Reject the PNG before decode if it's larger than this. Compressed PNGs above
# 64 MiB are almost certainly bogus for a screenshot upload.
_MAX_PNG_BYTES = 64 * 1024 * 1024


class ImageTooLargeError(Exception):
    """Uploaded image exceeds the size limit allowed for hashing."""


def hash_image(png_bytes: bytes) -> str:
    """Decode PNG to RGBA pixels and return the BLAKE3 hex digest."""
    if len(png_bytes) > _MAX_PNG_BYTES:
        raise ImageTooLargeError(f"PNG is {len(png_bytes)} bytes, exceeds {_MAX_PNG_BYTES} limit")
    img = Image.open(io.BytesIO(png_bytes))
    img.load()
    return blake3(img.convert("RGBA").tobytes()).hexdigest()
