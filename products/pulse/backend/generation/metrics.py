def per_day_rate(values: list[float]) -> float:
    """Average per-day rate over the values actually read — a live window can be shorter than
    period_days when data is sparse, and a delta must agree with the rates stated beside it.

    Empty input averages to 0.0 rather than raising: callers guard against it today, but this
    is exported and a zero-day window is a rate of zero, not an error.
    """
    if not values:
        return 0.0
    return float(sum(values)) / len(values)


def pct_delta(current: float, previous: float) -> float | None:
    """Then-vs-now percentage delta; None off a zero baseline — meaningless, not infinite.

    Deliberately different from score_movement's volume floor: this compares against a
    snapshot or prior window, it is not a significance test.
    """
    if not previous:
        return None
    return round(((current - previous) / previous) * 100.0, 1)


def rate_summary(rate: float) -> str:
    return f"{rate:.1f}/day avg"
