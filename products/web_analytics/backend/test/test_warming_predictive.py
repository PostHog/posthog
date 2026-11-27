from datetime import UTC, datetime

from django.test import SimpleTestCase

from products.web_analytics.backend.warming.predictive import ShapeDemand


def _at(day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=UTC)


class TestShapeDemand(SimpleTestCase):
    def test_features_follow_the_training_definitions(self) -> None:
        shape_hours = [
            _at(18, 10),
            _at(18, 9),
            _at(18, 8),
            _at(17, 13),
            _at(17, 10),
            _at(11, 11),
            _at(11, 9),
        ]
        project_hours = {*shape_hours, _at(18, 3), _at(17, 9)}

        demand = ShapeDemand.from_history(
            shape_hours=shape_hours, project_hours=project_hours, now=datetime(2026, 11, 18, 10, 30, tzinfo=UTC)
        )

        assert demand == ShapeDemand(
            hours_since_last=1,
            hours_read_4h=2,
            hours_read_1d=4,
            hours_read_7d=5,
            active_days_7d=3,
            same_window_days_7d=2,
            project_active_hours_1d=5,
            project_active_last_hour=True,
            window_start_hour=8,
            weekend=False,
        )

    def test_a_daily_habit_clears_the_default_threshold_and_an_unread_shape_does_not(self) -> None:
        now = datetime(2026, 11, 18, 10, 30, tzinfo=UTC)
        habitual = ShapeDemand.from_history(
            shape_hours=[_at(day, 10) for day in range(11, 18)], project_hours=set(), now=now
        )
        absent = ShapeDemand.from_history(shape_hours=[], project_hours=set(), now=now)

        assert absent.hours_since_last == 169
        assert absent.request_probability() < 0.2 < habitual.request_probability()
