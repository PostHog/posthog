import json
import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).parent / "investigate-metric" / "scripts" / "compare_to_prior_periods.py"

# Four weeks of a weekday-shaped metric. Thursday is the low weekday, so a terminal
# Thursday of 530 sits at 53% of the prior Thursdays' minimum. In that range the value
# alone cannot separate a half-elapsed bucket from a real drop.
WEEKDAY_BASE = {0: 1800, 1: 1850, 2: 1820, 3: 1000, 4: 1400, 5: 680, 6: 870}
HALF_DAY_ELAPSED = 530
NEAR_TOTAL_OUTAGE = 80


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compare_to_prior_periods", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = load_script()


def build_payload(
    days: list[str],
    values: list[float],
    interval: str,
    stamps: list[str] | None = None,
    offset: str = "-07:00",
) -> dict:
    """A trends response shaped like the MCP one: bare `days`, offset `action.days`."""
    stamps = stamps or [f"{d}T00:00:00{offset}" for d in days]
    return {
        "results": [
            {
                "data": values,
                "days": days,
                "label": "$pageview",
                "filter": {
                    "interval": interval,
                    "date_from": stamps[0],
                    "date_to": stamps[-1],
                },
                "action": {"days": stamps},
            }
        ]
    }


def weekday_payload(terminal: float) -> dict:
    start = date.fromisoformat("2026-08-14")
    days = [(start + timedelta(days=i)).isoformat() for i in range(28)]
    values = [float(WEEKDAY_BASE[(start + timedelta(days=i)).weekday()]) for i in range(28)]
    values[-1] = terminal
    return build_payload(days, values, "day")


def table_row(out: str, moment: str) -> str:
    """The results-table row for `moment`. The window header names it too."""
    return next(line for line in out.splitlines() if line.startswith("|") and moment in line)


def run(monkeypatch, capsys, tmp_path: Path, payload: dict, now: str) -> str:
    payload_file = tmp_path / "query_result.json"
    payload_file.write_text(json.dumps(payload))
    monkeypatch.setenv("NOW", now)
    monkeypatch.setattr("sys.argv", ["compare_to_prior_periods.py", str(payload_file)])
    assert SCRIPT.main() == 0
    return capsys.readouterr().out


@pytest.mark.parametrize(
    "now",
    [
        "2026-09-10T12:00:00-07:00",  # midday in the project's own zone
        "2026-09-10T23:00:00-07:00",  # late in the project's own day
        "2026-09-11T09:00:00+03:00",  # the same instant, written in another zone
    ],
)
def test_in_progress_terminal_day_is_excluded_from_the_anomaly_count(monkeypatch, capsys, tmp_path, now):
    out = run(monkeypatch, capsys, tmp_path, weekday_payload(HALF_DAY_ELAPSED), now=now)

    terminal_row = table_row(out, "2026-09-10")
    assert "PARTIAL" in terminal_row
    assert "BELOW" not in terminal_row
    assert "likely normal seasonality" in out
    assert "left out of the count" in out


@pytest.mark.parametrize("terminal", [HALF_DAY_ELAPSED, NEAR_TOTAL_OUTAGE])
def test_completed_terminal_day_keeps_its_anomaly_verdict(monkeypatch, capsys, tmp_path, terminal):
    out = run(monkeypatch, capsys, tmp_path, weekday_payload(terminal), now="2026-09-11T08:00:00-07:00")

    terminal_row = table_row(out, "2026-09-10")
    assert "BELOW" in terminal_row
    assert "PARTIAL" not in out
    assert "1 completed weekday(s) outside" in out


@pytest.mark.parametrize(
    ("interval", "days"),
    [
        ("month", [f"2026-{month:02d}-01" for month in range(3, 10)]),
        ("quarter", [f"{y}-{m:02d}-01" for y in (2025, 2026) for m in (1, 4, 7, 10)][:7]),
        ("year", [f"{year}-01-01" for year in range(2020, 2027)]),
    ],
)
def test_in_progress_terminal_period_is_excluded_from_the_anomaly_count(monkeypatch, capsys, tmp_path, interval, days):
    payload = build_payload(days, [50_000.0, 52_000.0, 51_000.0, 53_000.0, 49_000.0, 50_500.0, 9_000.0], interval)

    out = run(monkeypatch, capsys, tmp_path, payload, now="2026-09-10T12:00:00-07:00")

    assert "PARTIAL" in table_row(out, days[-1])
    assert "within normal variance" in out


@pytest.mark.parametrize(
    ("interval", "step"),
    [("minute", timedelta(minutes=1)), ("second", timedelta(seconds=1))],
)
def test_sub_day_rows_keep_their_time_of_day(monkeypatch, capsys, tmp_path, interval, step):
    start = datetime(2026, 9, 10, 6, 0)
    moments = [start + i * step for i in range(70)]
    payload = build_payload(
        [m.strftime("%Y-%m-%d %H:%M:%S") for m in moments],
        [500.0] * 70,
        interval,
        stamps=[m.strftime("%Y-%m-%dT%H:%M:%S-07:00") for m in moments],
    )

    out = run(monkeypatch, capsys, tmp_path, payload, now="2026-09-10T08:00:00-07:00")

    rows = [line for line in out.splitlines() if line.startswith("| 2026-09-10")]
    assert len(rows) == 60
    assert len({line.split("|")[1].strip() for line in rows}) == 60
