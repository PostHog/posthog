"""Grafana display settings mapped to the metrics panel settings: units, color thresholds and reducers."""

from __future__ import annotations

import math
from typing import Any

from posthog.dataclasses import frozen

from products.metrics.backend.dashboard_import.colors import map_color
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
    "cps": "{count}/s",
    "/s": "1/s",
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


@frozen
class MappedUnit:
    unit: str | None
    # Why the unit is lost, when it is.
    note: str | None = None


def map_unit(grafana_unit: Any) -> MappedUnit:
    """The UCUM unit for a Grafana unit id, and a note when the unit cannot be kept."""
    if not isinstance(grafana_unit, str):
        return MappedUnit(unit=None)
    if grafana_unit in _UNITS:
        return MappedUnit(unit=_UNITS[grafana_unit])
    return MappedUnit(unit=None, note=f'The unit "{grafana_unit}" is not available, so the panel shows plain numbers.')


def agent_unit(unit: str | None) -> str | None:
    """The UCUM unit for a unit that an agent read from a screenshot. It sometimes writes a Grafana unit id."""
    if unit is None:
        return None
    return _UNITS.get(unit, unit)


def map_reducer(calculation: Any) -> tuple[Reducer | None, str | None]:
    if not isinstance(calculation, str) or not calculation:
        return None, None
    if calculation in _REDUCERS:
        return _REDUCERS[calculation], None
    return "last", f'The "{calculation}" calculation is not available, so the panel shows the last value.'


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | str):
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return None
        # JSON cannot hold NaN or infinity, and Grafana uses neither as a real bound.
        return number if math.isfinite(number) else None
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
