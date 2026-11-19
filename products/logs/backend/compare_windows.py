import datetime as dt

from posthog.dataclasses import frozen

_SHIFTS = {"previous_day": dt.timedelta(days=1), "previous_week": dt.timedelta(days=7)}


@frozen
class Window:
    date_from: dt.datetime
    date_to: dt.datetime


def baseline_bounds(compare: str, date_from: dt.datetime, date_to: dt.datetime) -> Window | None:
    if compare == "previous_period":
        return Window(date_from=date_from - (date_to - date_from), date_to=date_from)
    shift = _SHIFTS.get(compare)
    return Window(date_from=date_from - shift, date_to=date_to - shift) if shift else None
