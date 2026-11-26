import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Literal

import posthoganalytics

from posthog.dataclasses import frozen

PREDICTIVE_WARMING_FLAG = "web-analytics-predictive-warming"

WarmingArm = Literal["predictive", "current"]

HISTORY_HOURS = 7 * 24
READ_HISTORY_HOURS = HISTORY_HOURS + 1
WINDOW_HOURS = 4

_INTERCEPT = -3.71938
_HOURS_SINCE_LAST = -0.314729
_HOURS_READ_4H = 0.119018
_HOURS_READ_1D = 0.932349
_HOURS_READ_7D = 0.045208
_ACTIVE_DAYS_7D = 0.249315
_SAME_WINDOW_DAYS_7D = 1.477505
_PROJECT_ACTIVE_HOURS_1D = -0.055070
_PROJECT_ACTIVE_LAST_HOUR = 0.223276
_WINDOW_START_HOUR = {4: 0.217988, 8: 0.375413, 12: 0.401285, 16: 0.280829, 20: 0.122046}
_WEEKEND = -0.304184


@frozen
class ShapeDemand:
    hours_since_last: float
    hours_read_4h: int
    hours_read_1d: int
    hours_read_7d: int
    active_days_7d: int
    same_window_days_7d: int
    project_active_hours_1d: int
    project_active_last_hour: bool
    window_start_hour: int
    weekend: bool

    @classmethod
    def from_history(
        cls, *, shape_hours: Iterable[datetime], project_hours: set[datetime], now: datetime
    ) -> "ShapeDemand":
        decision = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        history_start = decision - timedelta(hours=HISTORY_HOURS)
        past = [hour for hour in shape_hours if history_start <= hour < decision]

        def hours_within(hours: int) -> int:
            return sum(1 for hour in past if hour >= decision - timedelta(hours=hours))

        def read_in_window(days_ago: int) -> bool:
            window_start = decision - timedelta(days=days_ago)
            return any(window_start <= hour < window_start + timedelta(hours=WINDOW_HOURS) for hour in past)

        return cls(
            hours_since_last=min(
                (decision - max(past)).total_seconds() / 3600 if past else READ_HISTORY_HOURS, READ_HISTORY_HOURS
            ),
            hours_read_4h=hours_within(WINDOW_HOURS),
            hours_read_1d=hours_within(24),
            hours_read_7d=len(past),
            active_days_7d=len({hour.date() for hour in past}),
            same_window_days_7d=sum(1 for days_ago in range(1, 8) if read_in_window(days_ago)),
            project_active_hours_1d=sum(
                1 for hour in project_hours if decision - timedelta(hours=24) <= hour < decision
            ),
            project_active_last_hour=(decision - timedelta(hours=1)) in project_hours,
            window_start_hour=(decision.hour // WINDOW_HOURS) * WINDOW_HOURS,
            weekend=decision.isoweekday() >= 6,
        )

    def request_probability(self) -> float:
        logit = (
            _INTERCEPT
            + _HOURS_SINCE_LAST * math.log1p(self.hours_since_last)
            + _HOURS_READ_4H * math.log1p(self.hours_read_4h)
            + _HOURS_READ_1D * math.log1p(self.hours_read_1d)
            + _HOURS_READ_7D * math.log1p(self.hours_read_7d)
            + _ACTIVE_DAYS_7D * math.log1p(self.active_days_7d)
            + _SAME_WINDOW_DAYS_7D * math.log1p(self.same_window_days_7d)
            + _PROJECT_ACTIVE_HOURS_1D * math.log1p(self.project_active_hours_1d)
            + _PROJECT_ACTIVE_LAST_HOUR * self.project_active_last_hour
            + _WINDOW_START_HOUR.get(self.window_start_hour, 0.0)
            + _WEEKEND * self.weekend
        )
        return 1 / (1 + math.exp(-logit))


def warming_arm(team_id: int) -> WarmingArm:
    try:
        enabled = posthoganalytics.feature_enabled(
            PREDICTIVE_WARMING_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        return "current"
    return "predictive" if enabled else "current"
