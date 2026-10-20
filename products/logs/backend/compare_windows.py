import datetime as dt

COMPARE_MODES = ("none", "previous_period", "previous_day", "previous_week")
_SHIFTS = {"previous_day": dt.timedelta(days=1), "previous_week": dt.timedelta(days=7)}


def baseline_bounds(
    compare: str, date_from: dt.datetime, date_to: dt.datetime
) -> tuple[dt.datetime, dt.datetime] | None:
    if compare == "previous_period":
        return date_from - (date_to - date_from), date_from
    shift = _SHIFTS.get(compare)
    return (date_from - shift, date_to - shift) if shift else None
