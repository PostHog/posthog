from datetime import UTC, datetime

import time_machine

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.surveys.backend.responses.stats import StatsWindow, validate_and_parse_dates

NOW = datetime(2026, 3, 15, 12, 30, tzinfo=UTC)  # a Sunday
SAO_PAULO = "America/Sao_Paulo"  # UTC-3
SUNDAY, MONDAY = 0, 1


def _team(timezone: str = "UTC", week_start_day: int | None = None) -> Team:
    return Team(timezone=timezone, week_start_day=week_start_day)


@time_machine.travel(NOW, tick=False)
class TestValidateAndParseDates(SimpleTestCase):
    @parameterized.expand(
        [
            ("iso_utc", "2026-03-01T10:00:00Z", _team(), datetime(2026, 3, 1, 10, tzinfo=UTC)),
            ("iso_offset", "2026-03-01T02:00:00+02:00", _team(), datetime(2026, 3, 1, tzinfo=UTC)),
            ("naive_iso_in_project_tz", "2026-03-01T00:00:00", _team(SAO_PAULO), datetime(2026, 3, 1, 3, tzinfo=UTC)),
            ("days_snap_to_start_of_day", "-7d", _team(), datetime(2026, 3, 8, tzinfo=UTC)),
            ("days_in_project_tz", "-7d", _team(SAO_PAULO), datetime(2026, 3, 8, 3, tzinfo=UTC)),
            ("hours_snap_to_start_of_hour", "-24h", _team(), datetime(2026, 3, 14, 12, tzinfo=UTC)),
            ("months", "-1m", _team(), datetime(2026, 2, 15, tzinfo=UTC)),
            ("month_start", "mStart", _team(), datetime(2026, 3, 1, tzinfo=UTC)),
            ("week_start_sunday", "wStart", _team(week_start_day=SUNDAY), datetime(2026, 3, 15, tzinfo=UTC)),
            ("week_start_monday", "wStart", _team(week_start_day=MONDAY), datetime(2026, 3, 9, tzinfo=UTC)),
        ]
    )
    def test_parses_date_from(self, _name: str, value: str, team: Team, expected: datetime) -> None:
        assert validate_and_parse_dates(value, None, team) == StatsWindow(date_from=expected, date_to=None)

    @parameterized.expand(
        [
            ("iso_keeps_exact_time", "2026-03-10T10:00:00Z", _team(), datetime(2026, 3, 10, 10, tzinfo=UTC)),
            ("calendar_day_is_inclusive", "2026-03-10", _team(), datetime(2026, 3, 10, 23, 59, 59, 999999, tzinfo=UTC)),
            ("days_snap_to_end_of_day", "-1d", _team(), datetime(2026, 3, 14, 23, 59, 59, 999999, tzinfo=UTC)),
            ("days_in_project_tz", "-1d", _team(SAO_PAULO), datetime(2026, 3, 15, 2, 59, 59, 999999, tzinfo=UTC)),
            ("hours_keep_time_of_day", "-24h", _team(), datetime(2026, 3, 14, 12, 30, tzinfo=UTC)),
            (
                "week_end_monday",
                "wEnd",
                _team(week_start_day=MONDAY),
                datetime(2026, 3, 15, 23, 59, 59, 999999, tzinfo=UTC),
            ),
        ]
    )
    def test_parses_date_to(self, _name: str, value: str, team: Team, expected: datetime) -> None:
        assert validate_and_parse_dates(None, value, team) == StatsWindow(date_from=None, date_to=expected)

    def test_same_relative_day_covers_the_whole_day(self) -> None:
        assert validate_and_parse_dates("dStart", "dStart", _team()) == StatsWindow(
            date_from=datetime(2026, 3, 15, tzinfo=UTC),
            date_to=datetime(2026, 3, 15, 23, 59, 59, 999999, tzinfo=UTC),
        )

    @parameterized.expand(
        [
            ("words", "yesterday"),
            ("phrase", "7 days ago"),
            ("unknown_unit", "-7x"),
            ("bare_number", "7"),
            ("out_of_range", "-99999999d"),
        ]
    )
    def test_rejects_unparseable_date(self, _name: str, value: str) -> None:
        with self.assertRaisesRegex(ValueError, "relative date such as -7d"):
            validate_and_parse_dates(value, None, _team())

    def test_rejects_inverted_relative_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "date_from must be before date_to"):
            validate_and_parse_dates("-1d", "-7d", _team())
