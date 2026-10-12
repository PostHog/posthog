"""Grafana display settings mapped to the metrics panel settings: units, color thresholds and reducers."""

from __future__ import annotations

import re
import colorsys
from typing import Any

from products.metrics.backend.dashboard_import.spec import Reducer, Threshold

# Grafana unit ids to UCUM units that the metrics panels format. A unit that is not here shows plain numbers.
_UNITS: dict[str, str | None] = {
    "": None,
    "none": None,
    "short": None,
    "sishort": None,
    "locale": None,
    "s": "s",
    "dtdurations": "s",
    "ms": "ms",
    "dtdurationms": "ms",
    "µs": "us",
    "us": "us",
    "ns": "ns",
    "bytes": "By",
    "decbytes": "By",
    "kbytes": "KiBy",
    "mbytes": "MiBy",
    "gbytes": "GiBy",
    "Bps": "By/s",
    "binBps": "By/s",
    "decBps": "By/s",
    "percent": "%",
    "percentunit": "1",
    "reqps": "{req}/s",
    "rps": "{read}/s",
    "wps": "{write}/s",
    "iops": "{io}/s",
    "ops": "{op}/s",
    "pps": "{packet}/s",
    "hertz": "1/s",
}

_REDUCERS: dict[str, Reducer] = {
    "lastNotNull": "last",
    "last": "last",
    "current": "last",
    "mean": "mean",
    "avg": "mean",
    "max": "max",
    "min": "min",
    "sum": "sum",
    "total": "sum",
    "delta": "delta",
    "diff": "delta",
}

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


def map_unit(grafana_unit: Any) -> tuple[str | None, str | None]:
    """The UCUM unit for a Grafana unit id, and a note when the unit cannot be kept."""
    if not isinstance(grafana_unit, str):
        return None, None
    if grafana_unit in _UNITS:
        return _UNITS[grafana_unit], None
    return None, f'The unit "{grafana_unit}" is not available, so the panel shows plain numbers.'


def map_reducer(calculation: Any) -> tuple[Reducer | None, str | None]:
    if not isinstance(calculation, str) or not calculation:
        return None, None
    if calculation in _REDUCERS:
        return _REDUCERS[calculation], None
    return "last", f'The "{calculation}" calculation is not available, so the panel shows the last value.'


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


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def map_thresholds(steps: Any) -> list[Threshold]:
    """Grafana threshold steps to color bands. Grafana's base step has no value and colors everything below."""
    if not isinstance(steps, list):
        return []
    valued = [
        (number, map_color(step.get("color")))
        for step in steps
        if isinstance(step, dict) and (number := _number(step.get("value"))) is not None
    ]
    base = next(
        (map_color(step.get("color")) for step in steps if isinstance(step, dict) and step.get("value") is None),
        None,
    )
    thresholds = [Threshold(color=color, value=value) for value, color in valued]
    if base is not None:
        lowest = min((value for value, _ in valued), default=0.0)
        thresholds.insert(0, Threshold(color=base, value=lowest - 1 if valued else 0.0))
    return thresholds


def legacy_thresholds(thresholds: Any, colors: Any) -> list[Threshold]:
    """Singlestat thresholds such as "50,80" with three colors, as color bands."""
    if not isinstance(thresholds, str) or not isinstance(colors, list):
        return []
    values = [number for part in thresholds.split(",") if (number := _number(part.strip())) is not None]
    if not values or len(colors) < len(values) + 1:
        return []
    steps: list[dict[str, Any]] = [{"color": colors[0], "value": None}]
    steps.extend({"color": colors[index + 1], "value": value} for index, value in enumerate(values))
    return map_thresholds(steps)


def axis_bound(value: Any) -> float | None:
    return _number(value)
