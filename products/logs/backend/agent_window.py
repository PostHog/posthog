import datetime as dt


def utc_iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    value = value.astimezone(dt.UTC)
    timespec = "seconds" if value.microsecond == 0 else "milliseconds"
    return value.replace(tzinfo=None).isoformat(timespec=timespec) + "Z"


def window_echo(
    current: tuple[dt.datetime, dt.datetime], baseline: tuple[dt.datetime, dt.datetime] | None = None
) -> dict:
    window: dict = {"current": {"from": utc_iso(current[0]), "to": utc_iso(current[1])}}
    if baseline is not None:
        window["baseline"] = {"from": utc_iso(baseline[0]), "to": utc_iso(baseline[1])}
    window["timezone"] = "UTC"
    return window
