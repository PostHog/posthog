"""Color tokens for metrics threshold bands, and the mapping from Grafana colors to them."""

from __future__ import annotations

import re
import colorsys
from typing import Any

# The tokens that have a CSS variable in both themes. The metrics panels capture an error for any other value.
THRESHOLD_COLORS: frozenset[str] = frozenset(
    {"success", "warning", "danger", "blue", "purple", *(f"data-color-{index}" for index in range(1, 16))}
)

_NAMED_COLORS: tuple[tuple[str, str], ...] = (
    ("green", "success"),
    ("red", "danger"),
    ("orange", "warning"),
    ("yellow", "warning"),
    ("blue", "blue"),
    ("purple", "purple"),
)
_DEFAULT_COLOR = "data-color-1"
_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def _hue_color(red: int, green: int, blue: int) -> str:
    hue, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    if saturation < 0.15 or lightness < 0.1 or lightness > 0.95:
        return _DEFAULT_COLOR
    degrees = hue * 360
    if degrees < 20 or degrees >= 330:
        return "danger"
    if degrees < 70:
        return "warning"
    if degrees < 170:
        return "success"
    if degrees < 260:
        return "blue"
    return "purple"


def map_color(color: Any) -> str:
    """A color token that works in the light and the dark theme, for a Grafana color name or code."""
    if not isinstance(color, str):
        return _DEFAULT_COLOR
    lowered = color.strip().lower()
    for word, token in _NAMED_COLORS:
        if word in lowered:
            return token
    if hex_match := _HEX.match(lowered):
        digits = hex_match.group(1)
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        return _hue_color(int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
    if rgb_match := _RGB.match(lowered):
        return _hue_color(*(min(int(part), 255) for part in rgb_match.groups()))
    return _DEFAULT_COLOR
