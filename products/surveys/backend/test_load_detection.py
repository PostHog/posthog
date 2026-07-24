from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.surveys.backend.load_detection import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_OVERLOAD_THRESHOLD,
    DEFAULT_WINDOW_SECONDS,
    MAX_WINDOW_SECONDS,
    MIN_OVERLOAD_THRESHOLD,
    resolve_load_detector_config,
)

DEFAULTS = {
    "window_seconds": DEFAULT_WINDOW_SECONDS,
    "overload_threshold": DEFAULT_OVERLOAD_THRESHOLD,
    "lookback_days": DEFAULT_LOOKBACK_DAYS,
}


class TestResolveLoadDetectorConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_survey_config", None, None, DEFAULTS),
            ("no_load_detector_key", {"appearance": {"whiteLabel": True}}, None, DEFAULTS),
            ("load_detector_not_a_dict", {"load_detector": "bogus"}, None, DEFAULTS),
            (
                "saved_values_used",
                {"load_detector": {"window_seconds": 7200, "overload_threshold": 3, "lookback_days": 7}},
                None,
                {"window_seconds": 7200, "overload_threshold": 3, "lookback_days": 7},
            ),
            (
                "saved_values_clamped_or_defaulted",
                {"load_detector": {"window_seconds": 10**12, "overload_threshold": 0, "lookback_days": "bogus"}},
                None,
                {
                    "window_seconds": MAX_WINDOW_SECONDS,
                    "overload_threshold": MIN_OVERLOAD_THRESHOLD,
                    "lookback_days": DEFAULT_LOOKBACK_DAYS,
                },
            ),
            (
                "overrides_beat_saved_values",
                {"load_detector": {"window_seconds": 7200, "overload_threshold": 3}},
                {"window_seconds": 600},
                {"window_seconds": 600, "overload_threshold": 3, "lookback_days": DEFAULT_LOOKBACK_DAYS},
            ),
        ]
    )
    def test_resolve(self, _name, survey_config, overrides, expected):
        team = Team(survey_config=survey_config)
        assert resolve_load_detector_config(team, overrides=overrides) == expected
