from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.test.persons import create_person

from products.feature_flags.backend.flag_windows.baseline import BaselineHour, HourErrors, error_baseline

# Half past the hour, so that an implementation that counts clock hours reads the wrong events. Edit times carry
# fractions of a second.
START = datetime(2026, 10, 1, 12, 30, 0, 500000, tzinfo=UTC)
WEEK = timedelta(weeks=1)

# (distinct id, event, time, event properties)
Event = tuple[str, str, datetime, dict[str, Any]]


def _errors(active: int, with_errors: int) -> HourErrors:
    return HourErrors(active=active, with_errors=with_errors)


NONE = _errors(0, 0)


class TestErrorBaseline(ClickhouseTestMixin, BaseTest):
    def _send(self, events: list[Event]) -> None:
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, _, _, _ in events):
            create_person(team=self.team, distinct_ids=[distinct_id])
        for distinct_id, event, timestamp, properties in events:
            _create_event(
                team=self.team, event=event, distinct_id=distinct_id, timestamp=timestamp, properties=properties
            )
        flush_persons_and_events()

    def test_each_hour_counts_the_people_with_events_and_with_errors_in_the_same_hour_of_each_earlier_week(
        self,
    ) -> None:
        self._send(
            [
                ("person-1", "$pageview", START - WEEK + timedelta(minutes=10), {}),
                ("person-1", "$exception", START - WEEK + timedelta(minutes=20), {}),
                ("person-2", "$exception", START - WEEK + timedelta(minutes=70), {}),
                # People count once, however many events they send.
                ("person-3", "$pageview", START - 2 * WEEK + timedelta(minutes=5), {}),
                ("person-3", "$pageview", START - 2 * WEEK + timedelta(minutes=6), {}),
                ("person-4", "$exception", START - 4 * WEEK + timedelta(minutes=119), {}),
                # Just before the end of the first hour.
                ("person-7", "$pageview", START - 3 * WEEK + timedelta(minutes=60, milliseconds=-300), {}),
                # In the clock hour of the window start, but before the window start.
                ("person-5", "$pageview", START - WEEK - timedelta(minutes=5), {}),
                # After the window's hours.
                ("person-5", "$pageview", START - WEEK + timedelta(minutes=120), {}),
                # In the window itself, and in a week older than the baseline.
                ("person-6", "$exception", START + timedelta(minutes=10), {}),
                ("person-6", "$exception", START - 5 * WEEK + timedelta(minutes=10), {}),
            ]
        )

        baseline = error_baseline(self.team, [None], START, START + timedelta(minutes=90))

        assert baseline == {
            None: [
                BaselineHour(start=START, weeks=(_errors(1, 1), _errors(1, 0), _errors(1, 0), NONE)),
                BaselineHour(start=START + timedelta(hours=1), weeks=(_errors(1, 1), NONE, NONE, _errors(1, 1))),
            ]
        }

    def test_a_group_flag_counts_the_groups_on_the_events_next_to_the_persons(self) -> None:
        hour_a_week_earlier = START - WEEK + timedelta(minutes=10)
        self._send(
            [
                ("person-1", "$pageview", hour_a_week_earlier, {"$group_0": "org-a"}),
                ("person-2", "$exception", hour_a_week_earlier, {"$group_0": "org-a"}),
                ("person-3", "$pageview", hour_a_week_earlier, {"$group_0": "org-b"}),
                # An event without the group counts only for persons.
                ("person-4", "$exception", hour_a_week_earlier, {}),
            ]
        )

        baseline = error_baseline(self.team, [0, None], START, START + timedelta(hours=1), weeks=1)

        assert baseline == {
            0: [BaselineHour(start=START, weeks=(_errors(2, 1),))],
            None: [BaselineHour(start=START, weeks=(_errors(4, 2),))],
        }
