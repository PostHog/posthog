import datetime as dt

import pytest

from products.replay_vision.backend.temporal.sweep_cadence import SweepCadenceInputs, sweep_interval

NOW = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.UTC)
LONG_AGO = NOW - dt.timedelta(days=30)


def _inputs(**overrides: object) -> SweepCadenceInputs:
    fields: dict[str, object] = {
        "created_at": LONG_AGO,
        "updated_at": LONG_AGO,
        "last_found_candidates_at": None,
        "sweep_paused_until": None,
        "throttle_factor": 1,
        "has_enabled_alert": False,
    }
    fields.update(overrides)
    return SweepCadenceInputs(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides, expected_minutes",
    [
        ({}, 60),
        ({"last_found_candidates_at": NOW - dt.timedelta(minutes=30)}, 5),
        ({"last_found_candidates_at": NOW - dt.timedelta(hours=3)}, 15),
        ({"last_found_candidates_at": NOW - dt.timedelta(hours=10)}, 60),
        ({"created_at": NOW - dt.timedelta(hours=2)}, 5),
        ({"updated_at": NOW - dt.timedelta(hours=2)}, 5),
        ({"has_enabled_alert": True}, 5),
        ({"has_enabled_alert": True, "throttle_factor": 3}, 15),
        ({"has_enabled_alert": True, "throttle_factor": 4}, 30),
        ({"has_enabled_alert": True, "throttle_factor": 12}, 60),
        ({"sweep_paused_until": NOW - dt.timedelta(minutes=1)}, 60),
        ({"sweep_paused_until": NOW + dt.timedelta(minutes=1)}, None),
        ({"sweep_paused_until": NOW + dt.timedelta(minutes=1), "has_enabled_alert": True}, None),
    ],
)
def test_sweep_interval(overrides: dict[str, object], expected_minutes: int | None) -> None:
    interval = sweep_interval(_inputs(**overrides), NOW)
    assert (None if interval is None else interval / dt.timedelta(minutes=1)) == expected_minutes
