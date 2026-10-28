import datetime as dt

import pytest

from products.metrics.backend.query_interval import resolve_query_interval
from products.metrics.backend.variables import Variable

START = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    "interval, values, is_all, hours, expected, error",
    [
        (None, (), False, 168, None, None),
        ("minute_5", (), False, 168, "minute_5", None),
        ("$window", ("1h",), False, 168, "hour", None),
        ("${window}", ("15m",), False, 6, "minute_15", None),
        ("$window", ("1m",), False, 168, None, "larger duration.*shorter date range"),
        ("$window", ("1h", "6h"), False, 168, None, "Select one duration"),
        ("$window", ("1h",), True, 168, None, "Select one duration"),
        ("$window", ("invalid",), False, 168, None, "Invalid chart interval"),
        ("prefix$window", ("1h",), False, 168, None, "single variable reference"),
    ],
)
def test_interval_variable_keeps_the_selected_spacing(
    interval: str | None,
    values: tuple[str, ...],
    is_all: bool,
    hours: int,
    expected: str | None,
    error: str | None,
) -> None:
    variables = {"window": Variable(values=values, is_all=is_all, all_value=None, options=())}
    end = START + dt.timedelta(hours=hours)
    if error:
        with pytest.raises(ValueError, match=error):
            resolve_query_interval(interval, variables, START, end)
    else:
        assert resolve_query_interval(interval, variables, START, end) == expected
