"""Human-readable renderings of ClickHouse query metrics.

Kept local to this bundle on purpose: it is a standalone CLI that runs without
Django, so it cannot reach the formatters that live in the web app.
"""

from __future__ import annotations

_MS_PER_SECOND = 1000
_MS_PER_MINUTE = 60 * _MS_PER_SECOND
_BYTE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def format_duration_ms(milliseconds: float) -> str:
    """Render a duration as `840ms`, `31.4s`, or `2m 11s`."""
    if milliseconds < _MS_PER_SECOND:
        return f"{milliseconds:.0f}ms"
    if milliseconds < _MS_PER_MINUTE:
        return f"{milliseconds / _MS_PER_SECOND:.1f}s"
    minutes, remainder = divmod(round(milliseconds), _MS_PER_MINUTE)
    return f"{minutes}m {remainder // _MS_PER_SECOND}s"


def format_bytes(count: float) -> str:
    """Render a byte count in the largest binary unit that keeps it below 1024."""
    size = float(count)
    for unit in _BYTE_UNITS[:-1]:
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {_BYTE_UNITS[-1]}"
