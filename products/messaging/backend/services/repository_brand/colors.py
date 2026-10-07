import re
import math
from collections.abc import Callable

from posthog.dataclasses import frozen

from products.messaging.backend.services.repository_brand.tailwind_palette import (
    TAILWIND_V3_PALETTE,
    TAILWIND_V4_PALETTE,
)

ResolveVariable = Callable[[str], str | None]

MAX_VARIABLE_DEPTH = 6
MAX_COLOR_EXPRESSION_LENGTH = 120

NAMED_COLORS = {
    "white": "#ffffff",
    "black": "#000000",
    "red": "#ff0000",
    "blue": "#0000ff",
    "green": "#008000",
    "orange": "#ffa500",
    "purple": "#800080",
}

HEX = re.compile(r"#([0-9a-fA-F]{3,8})")
FUNCTION = re.compile(r"(rgba?|hsla?|oklch)\(\s*([^()]*)\)", re.IGNORECASE)
HSL_TRIPLET = re.compile(r"(-?[\d.]+)(?:deg)?\s+([\d.]+)%\s+([\d.]+)%")
RGB_TRIPLET = re.compile(r"(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})")
VARIABLE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)")
WRAPPED_VARIABLE = re.compile(r"(rgba?|hsla?|oklch)\(\s*var\(\s*(--[\w-]+)\s*\)\s*(?:/[^)]*)?\)", re.IGNORECASE)
SCSS_VARIABLE = re.compile(r"\$[\w-]+")
PALETTE_VARIABLE = re.compile(r"--color-([a-z]+)-(\d{2,3})")
PALETTE_THEME_FUNCTION = re.compile(r"theme\(\s*['\"]?colors\.([a-z]+)\.(\d{2,3})['\"]?\s*\)")
ALPHA_SUFFIX = re.compile(r"\s*/\s*[\d.]+%?\s*$")


def resolve_color(raw: str, resolve_variable: ResolveVariable, depth: int = 0) -> str | None:
    if depth > MAX_VARIABLE_DEPTH or len(raw) > MAX_COLOR_EXPRESSION_LENGTH:
        return None
    value = _strip_value(raw)
    if not value:
        return None
    if (literal := literal_color(value)) is not None:
        return literal
    if wrapped := WRAPPED_VARIABLE.fullmatch(value):
        inner = resolve_variable(wrapped.group(2))
        if inner is None:
            return None
        return literal_color(f"{wrapped.group(1)}({_strip_value(inner)})") or resolve_color(
            inner, resolve_variable, depth + 1
        )
    if variable := VARIABLE.fullmatch(value):
        target = resolve_variable(variable.group(1))
        if target is not None:
            return resolve_color(target, resolve_variable, depth + 1)
        if variable.group(2):
            return resolve_color(variable.group(2), resolve_variable, depth + 1)
        return palette_color_for_variable(variable.group(1))
    if SCSS_VARIABLE.fullmatch(value):
        target = resolve_variable(value)
        return resolve_color(target, resolve_variable, depth + 1) if target is not None else None
    if theme_reference := PALETTE_THEME_FUNCTION.fullmatch(value):
        return palette_color(theme_reference.group(1), theme_reference.group(2))
    return None


def literal_color(value: str) -> str | None:
    if len(value) > MAX_COLOR_EXPRESSION_LENGTH:
        return None
    try:
        if match := HEX.fullmatch(value):
            return _hex(match.group(1))
        if match := FUNCTION.fullmatch(value):
            return _function_color(match.group(1).lower(), match.group(2))
        if match := HSL_TRIPLET.fullmatch(value):
            return _hsl_to_rgb(float(match.group(1)), float(match.group(2)) / 100, float(match.group(3)) / 100).hex()
        if match := RGB_TRIPLET.fullmatch(value):
            return _Rgb(
                red=int(match.group(1)) / 255, green=int(match.group(2)) / 255, blue=int(match.group(3)) / 255
            ).hex()
    except (ValueError, IndexError, OverflowError):
        return None
    return NAMED_COLORS.get(value.lower())


def palette_color(name: str, shade: str = "500") -> str | None:
    return TAILWIND_V3_PALETTE.get(name, {}).get(shade)


def palette_color_for_variable(variable: str) -> str | None:
    match = PALETTE_VARIABLE.fullmatch(variable)
    return TAILWIND_V4_PALETTE.get(match.group(1), {}).get(match.group(2)) if match else None


def is_near_white(color: str) -> bool:
    return min(_Rgb.parse(color).channels()) > 230 / 255


def is_near_black(color: str) -> bool:
    return max(_Rgb.parse(color).channels()) < 64 / 255


def is_saturated(color: str) -> bool:
    channels = _Rgb.parse(color).channels()
    return max(channels) - min(channels) >= 0.12


def is_near_gray(color: str) -> bool:
    return not is_saturated(color) and not is_near_black(color)


def _strip_value(raw: str) -> str:
    value = raw.strip().strip("'\"`").strip()
    value = re.sub(r"\s*!default\s*$", "", value)
    return value.rstrip(";").strip()


def _hex(digits: str) -> str | None:
    if len(digits) in (3, 4):
        return "#" + "".join(character * 2 for character in digits[:3]).lower()
    if len(digits) in (6, 8):
        return "#" + digits[:6].lower()
    return None


def _function_color(name: str, arguments: str) -> str | None:
    parts = re.split(r"[\s,/]+", ALPHA_SUFFIX.sub("", arguments.strip()))
    if name.startswith("rgb"):
        return _Rgb(
            red=_number(parts[0], scale=255), green=_number(parts[1], scale=255), blue=_number(parts[2], scale=255)
        ).hex()
    if name.startswith("hsl"):
        return _hsl_to_rgb(_number(parts[0]), _number(parts[1], scale=100), _number(parts[2], scale=100)).hex()
    chroma_hue = _number(parts[2]) if parts[2] != "none" else 0.0
    return _oklch_to_rgb(_number(parts[0]), _number(parts[1]), chroma_hue).hex()


def _number(token: str, scale: float = 1.0) -> float:
    token = token.strip()
    if token.endswith("%"):
        return float(token[:-1]) / 100
    if token.endswith("deg"):
        return float(token[:-3])
    return float(token) / scale


@frozen
class _Rgb:
    red: float
    green: float
    blue: float

    @classmethod
    def parse(cls, color: str) -> "_Rgb":
        return cls(red=int(color[1:3], 16) / 255, green=int(color[3:5], 16) / 255, blue=int(color[5:7], 16) / 255)

    def channels(self) -> list[float]:
        return [self.red, self.green, self.blue]

    def hex(self) -> str:
        return "#" + "".join(f"{max(0, min(255, round(channel * 255))):02x}" for channel in self.channels())


def _hsl_to_rgb(hue_degrees: float, saturation_ratio: float, lightness: float) -> _Rgb:
    if saturation_ratio == 0:
        return _Rgb(red=lightness, green=lightness, blue=lightness)
    position = (hue_degrees % 360) / 360
    upper = (
        lightness * (1 + saturation_ratio)
        if lightness < 0.5
        else lightness + saturation_ratio - lightness * saturation_ratio
    )
    lower = 2 * lightness - upper

    def channel(offset: float) -> float:
        offset %= 1
        if offset < 1 / 6:
            return lower + (upper - lower) * 6 * offset
        if offset < 1 / 2:
            return upper
        if offset < 2 / 3:
            return lower + (upper - lower) * (2 / 3 - offset) * 6
        return lower

    return _Rgb(red=channel(position + 1 / 3), green=channel(position), blue=channel(position - 1 / 3))


def _oklch_to_rgb(lightness: float, chroma: float, hue_degrees: float) -> _Rgb:
    a = chroma * math.cos(math.radians(hue_degrees))
    b = chroma * math.sin(math.radians(hue_degrees))
    long_cone = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    medium_cone = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    short_cone = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return _Rgb(
        red=_gamma_encode(4.0767416621 * long_cone - 3.3077115913 * medium_cone + 0.2309699292 * short_cone),
        green=_gamma_encode(-1.2684380046 * long_cone + 2.6097574011 * medium_cone - 0.3413193965 * short_cone),
        blue=_gamma_encode(-0.0041960863 * long_cone - 0.7034186147 * medium_cone + 1.7076147010 * short_cone),
    )


def _gamma_encode(channel: float) -> float:
    clamped = max(0.0, min(1.0, channel))
    return 12.92 * clamped if clamped <= 0.0031308 else 1.055 * clamped ** (1 / 2.4) - 0.055
