"""How far back a logs alert check reads. Light, so the event builders loaded at startup can use it."""


def rolling_check_lookback_minutes(window_minutes: int, cadence_minutes: int, period_count: int) -> int:
    """Total minutes of history covered by M cadence-stepped rolling windows."""
    return window_minutes + (period_count - 1) * cadence_minutes
