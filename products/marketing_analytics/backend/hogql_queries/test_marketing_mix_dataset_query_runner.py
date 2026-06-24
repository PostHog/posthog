import datetime

from parameterized import parameterized

from products.marketing_analytics.backend.hogql_queries.marketing_mix_dataset_query_runner import (
    SpendPanelRow,
    _calendar_controls,
    check_sufficiency,
)

_MONDAY = datetime.date(2025, 1, 6)


def _panel(num_weeks: int, channels_per_week: int, spend: float) -> list[SpendPanelRow]:
    rows: list[SpendPanelRow] = []
    for week_index in range(num_weeks):
        week = _MONDAY + datetime.timedelta(weeks=week_index)
        for channel_index in range(channels_per_week):
            rows.append(SpendPanelRow(week=week, channel=f"ch{channel_index}", spend=spend, impressions=0, clicks=0))
    return rows


class TestCheckSufficiency:
    @parameterized.expand(
        [
            # (num_weeks, channels_per_week, spend, expected_sufficient, expected_qualifying_weeks)
            ("exactly_52_weeks_two_material_channels", 52, 2, 200.0, True, 52),
            ("one_short_of_the_bar", 51, 2, 200.0, False, 51),
            ("single_channel_weeks_never_qualify", 60, 1, 200.0, False, 0),
            ("spend_below_threshold_is_not_material", 60, 2, 50.0, False, 0),
        ]
    )
    def test_check_sufficiency(
        self,
        _name: str,
        num_weeks: int,
        channels_per_week: int,
        spend: float,
        expected_sufficient: bool,
        expected_qualifying: int,
    ) -> None:
        # Guards the sufficiency gate: a regression that drops the ≥2-channel rule, the 52-week floor,
        # or the material-spend threshold would let MMM run on an unidentifiable panel.
        sufficient, qualifying = check_sufficiency(_panel(num_weeks, channels_per_week, spend))
        assert sufficient is expected_sufficient
        assert qualifying == expected_qualifying

    def test_qualifying_week_needs_two_distinct_channels_not_two_rows(self) -> None:
        # Two rows for the SAME channel in a week must not count as two material channels.
        week_rows = [
            SpendPanelRow(week=_MONDAY, channel="google", spend=200.0, impressions=0, clicks=0),
            SpendPanelRow(week=_MONDAY, channel="google", spend=200.0, impressions=0, clicks=0),
        ]
        _sufficient, qualifying = check_sufficiency(week_rows)
        assert qualifying == 0


class TestCalendarControls:
    @parameterized.expand(
        [
            # ISO week 52 (Dec 23 2024) is in the holiday set; ISO week 10 (Mar 3 2025) is not.
            ("holiday_week", datetime.date(2024, 12, 23), 52, 1),
            ("ordinary_week", datetime.date(2025, 3, 3), 10, 0),
        ]
    )
    def test_calendar_controls(self, _name: str, week: datetime.date, expected_woy: int, expected_holiday: int) -> None:
        week_of_year, is_holiday = _calendar_controls(week)
        assert week_of_year == expected_woy
        assert is_holiday == expected_holiday
