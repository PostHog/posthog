from datetime import UTC, date, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.test.persons import create_person

from products.feature_flags.backend.flag_windows.baseline import (
    BaselineHour,
    HourErrors,
    error_baseline,
    errors_by_hour,
)

DAY = date(2026, 10, 1)
MIDNIGHT = datetime(2026, 10, 1, tzinfo=UTC)
WEEK = timedelta(weeks=1)

# (distinct id, event, time, event properties)
Event = tuple[str, str, datetime, dict[str, Any]]


def _errors(active: int, with_errors: int) -> HourErrors:
    return HourErrors(active=active, with_errors=with_errors)


NONE = _errors(0, 0)


def _day(weeks: int, by_hour: dict[int, tuple[HourErrors, ...]]) -> list[BaselineHour]:
    return [
        BaselineHour(start=MIDNIGHT + timedelta(hours=hour), weeks=by_hour.get(hour, (NONE,) * weeks))
        for hour in range(24)
    ]


class TestErrorBaseline(ClickhouseTestMixin, BaseTest):
    def _send(self, events: list[Event]) -> None:
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, _, _, _ in events):
            create_person(team=self.team, distinct_ids=[distinct_id])
        for distinct_id, event, timestamp, properties in events:
            _create_event(
                team=self.team, event=event, distinct_id=distinct_id, timestamp=timestamp, properties=properties
            )
        flush_persons_and_events()

    def test_each_utc_hour_counts_the_people_with_events_and_with_errors_in_the_same_hour_of_each_earlier_week(
        self,
    ) -> None:
        # Hours in the team's timezone would put every event in the wrong hour.
        self.team.timezone = "America/New_York"
        self.team.save()
        self._send(
            [
                ("person-1", "$pageview", MIDNIGHT - WEEK + timedelta(minutes=10), {}),
                ("person-1", "$exception", MIDNIGHT - WEEK + timedelta(minutes=20), {}),
                ("person-2", "$exception", MIDNIGHT - WEEK + timedelta(minutes=70), {}),
                # People count once, however many events they send.
                ("person-3", "$pageview", MIDNIGHT - 2 * WEEK + timedelta(minutes=5), {}),
                ("person-3", "$pageview", MIDNIGHT - 2 * WEEK + timedelta(minutes=6), {}),
                ("person-4", "$pageview", MIDNIGHT - 3 * WEEK + timedelta(minutes=30), {}),
                ("person-5", "$exception", MIDNIGHT - 4 * WEEK + timedelta(hours=23, minutes=59), {}),
                # The days before and after the day in an earlier week.
                ("person-6", "$pageview", MIDNIGHT - WEEK - timedelta(minutes=5), {}),
                ("person-6", "$pageview", MIDNIGHT - WEEK + timedelta(hours=24, minutes=5), {}),
                # The day itself, and a week older than the baseline.
                ("person-7", "$exception", MIDNIGHT + timedelta(minutes=10), {}),
                ("person-7", "$exception", MIDNIGHT - 5 * WEEK + timedelta(minutes=10), {}),
            ]
        )

        baseline = error_baseline(self.team, [None], DAY)

        assert baseline == {
            None: _day(
                weeks=4,
                by_hour={
                    0: (_errors(1, 1), _errors(1, 0), _errors(1, 0), NONE),
                    1: (_errors(1, 1), NONE, NONE, NONE),
                    23: (NONE, NONE, NONE, _errors(1, 1)),
                },
            )
        }

    def test_a_group_flag_counts_the_groups_on_the_events_next_to_the_persons(self) -> None:
        hour_a_week_earlier = MIDNIGHT - WEEK + timedelta(minutes=10)
        self._send(
            [
                ("person-1", "$pageview", hour_a_week_earlier, {"$group_0": "org-a"}),
                ("person-2", "$exception", hour_a_week_earlier, {"$group_0": "org-a"}),
                ("person-3", "$pageview", hour_a_week_earlier, {"$group_0": "org-b"}),
                # An event without the group counts only for persons.
                ("person-4", "$exception", hour_a_week_earlier, {}),
            ]
        )

        baseline = error_baseline(self.team, [0, None], DAY, weeks=1)

        assert baseline == {
            0: _day(weeks=1, by_hour={0: (_errors(2, 1),)}),
            None: _day(weeks=1, by_hour={0: (_errors(4, 2),)}),
        }

    def test_the_day_itself_counts_each_utc_hour_without_the_earlier_weeks_or_the_next_day(self) -> None:
        # A day that starts at midnight in the team's timezone would read 04:00 to 04:00 UTC and count other events.
        self.team.timezone = "America/New_York"
        self.team.save()
        self._send(
            [
                ("person-1", "$pageview", MIDNIGHT + timedelta(minutes=10), {}),
                ("person-2", "$exception", MIDNIGHT + timedelta(minutes=20), {}),
                ("person-1", "$pageview", MIDNIGHT + timedelta(hours=5, minutes=1), {}),
                ("person-3", "$exception", MIDNIGHT - WEEK + timedelta(minutes=10), {}),
                ("person-3", "$exception", MIDNIGHT + timedelta(hours=24, minutes=5), {}),
            ]
        )

        errors = errors_by_hour(self.team, [None], DAY)

        by_hour = {0: _errors(2, 1), 5: _errors(1, 0)}
        assert errors == {None: [by_hour.get(hour, NONE) for hour in range(24)]}
