"""
Canonical image hashing for upload integrity verification.

Matches the CLI's hashing pipeline: PNG → sRGB RGBA → BLAKE3.
This ensures the server can verify that uploaded bytes correspond
to the content hash the CLI claimed.
"""

import io

from blake3 import blake3
from PIL import Image


def hash_image(png_bytes: bytes) -> str:
    """Decode PNG to RGBA pixels and return the BLAKE3 hex digest."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    return blake3(img.tobytes()).hexdigest()
