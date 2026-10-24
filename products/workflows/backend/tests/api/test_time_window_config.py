from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers

from products.workflows.backend.presentation.views.time_window_config import validate_time_window_config


class TestTimeWindowConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_day", {"day": "everyday"}, "day"),
            ("no_days", {"day": []}, "day"),
            ("unknown_weekday", {"day": ["not-a-weekday"]}, "day"),
            ("non_string_day", {"day": [False]}, "day"),
            ("missing_day", {"day": None}, "day"),
            ("invalid_hour", {"time": ["25:00", "26:00"]}, "time"),
            ("invalid_minute", {"time": ["09:75", "10:00"]}, "time"),
            ("missing_end", {"time": ["09:00"]}, "time"),
            ("invalid_timezone", {"timezone": "Not/AZone"}, "timezone"),
            ("invalid_fallback", {"fallback_timezone": "Not/AZone"}, "fallback_timezone"),
            ("invalid_timezone_type", {"timezone": []}, "timezone"),
            ("invalid_person_timezone", {"use_person_timezone": "false"}, "use_person_timezone"),
        ]
    )
    def test_rejects_unusable_settings(self, _name: str, changes: dict[str, object], field: str) -> None:
        config = {"day": "any", "time": ["09:00", "17:00"], **changes}
        with self.assertRaises(serializers.ValidationError) as error:
            validate_time_window_config(config)
        assert field in error.exception.detail["config"]

    @parameterized.expand(
        [
            ("daily", {"day": "any", "time": "any"}),
            ("weekdays", {"day": "weekday", "time": ["09:00", "17:00"]}),
            ("weekends", {"day": "weekend", "time": "any"}),
            ("selected_days", {"day": ["monday", "friday"], "time": "any"}),
            ("overnight", {"day": "any", "time": ["22:30", "01:15"]}),
            ("full_day", {"day": "any", "time": ["09:00", "09:00"]}),
            (
                "person_timezone",
                {
                    "day": "any",
                    "time": "any",
                    "timezone": None,
                    "use_person_timezone": True,
                    "fallback_timezone": "UTC",
                },
            ),
        ]
    )
    def test_accepts_supported_settings(self, _name: str, config: dict[str, object]) -> None:
        validate_time_window_config(config)

    def test_rejects_a_non_object_config(self) -> None:
        with self.assertRaises(serializers.ValidationError):
            validate_time_window_config([])
