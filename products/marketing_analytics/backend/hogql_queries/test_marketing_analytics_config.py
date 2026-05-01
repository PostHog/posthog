from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.exceptions import ValidationError

from posthog.schema import AttributionMode

from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import (
    MULTI_TOUCH_MODES,
    MarketingAnalyticsConfig,
)


class TestMarketingAnalyticsConfig(BaseTest):
    def _set_attribution_mode(self, mode: AttributionMode) -> None:
        # Access the cached_property to ensure the config exists, then update it
        ma_config = self.team.marketing_analytics_config
        ma_config.attribution_mode = mode.value
        ma_config.save()
        # Invalidate the cached_property so from_team reads fresh data
        try:
            del self.team.marketing_analytics_config
        except AttributeError:
            pass

    def test_from_team_defaults_to_last_touch(self):
        config = MarketingAnalyticsConfig.from_team(self.team)
        assert config.attribution_mode == AttributionMode.LAST_TOUCH
        assert config.attribution_window_days == 90
        assert not config.is_multi_touch

    @patch(
        "products.marketing_analytics.backend.hogql_queries.marketing_analytics_config.posthoganalytics.feature_enabled",
        return_value=True,
    )
    def test_from_team_multi_touch_flag_enabled_keeps_mode(self, mock_ff):
        self._set_attribution_mode(AttributionMode.LINEAR)
        config = MarketingAnalyticsConfig.from_team(self.team)

        assert config.attribution_mode == AttributionMode.LINEAR
        assert config.is_multi_touch
        mock_ff.assert_called_once()

    @patch(
        "products.marketing_analytics.backend.hogql_queries.marketing_analytics_config.posthoganalytics.feature_enabled",
        return_value=False,
    )
    def test_from_team_multi_touch_flag_disabled_falls_back_to_last_touch(self, mock_ff):
        self._set_attribution_mode(AttributionMode.TIME_DECAY)
        config = MarketingAnalyticsConfig.from_team(self.team)

        assert config.attribution_mode == AttributionMode.LAST_TOUCH
        assert not config.is_multi_touch

    @patch(
        "products.marketing_analytics.backend.hogql_queries.marketing_analytics_config.posthoganalytics.feature_enabled",
        return_value=None,
    )
    def test_from_team_multi_touch_flag_returns_none_falls_back(self, mock_ff):
        self._set_attribution_mode(AttributionMode.POSITION_BASED)
        config = MarketingAnalyticsConfig.from_team(self.team)

        # feature_enabled returns None when SDK can't reach the server;
        # `not None` is True, so we fall back to LAST_TOUCH
        assert config.attribution_mode == AttributionMode.LAST_TOUCH
        assert not config.is_multi_touch

    def test_from_team_single_touch_modes_skip_flag_check(self):
        self._set_attribution_mode(AttributionMode.FIRST_TOUCH)

        with patch(
            "products.marketing_analytics.backend.hogql_queries.marketing_analytics_config.posthoganalytics.feature_enabled",
        ) as mock_ff:
            config = MarketingAnalyticsConfig.from_team(self.team)

        assert config.attribution_mode == AttributionMode.FIRST_TOUCH
        mock_ff.assert_not_called()

    def test_is_multi_touch_property(self):
        config = MarketingAnalyticsConfig()

        config.attribution_mode = AttributionMode.LAST_TOUCH
        assert not config.is_multi_touch

        config.attribution_mode = AttributionMode.FIRST_TOUCH
        assert not config.is_multi_touch

        for mode in MULTI_TOUCH_MODES:
            config.attribution_mode = mode
            assert config.is_multi_touch, f"{mode} should be multi-touch"

    def test_attribution_mode_operator(self):
        config = MarketingAnalyticsConfig()

        config.attribution_mode = AttributionMode.LAST_TOUCH
        assert config.attribution_mode_operator == "arrayMax"

        config.attribution_mode = AttributionMode.FIRST_TOUCH
        assert config.attribution_mode_operator == "arrayMin"

        # Multi-touch modes fall back to arrayMax (used in fallback paths)
        config.attribution_mode = AttributionMode.LINEAR
        assert config.attribution_mode_operator == "arrayMax"

    def test_save_with_invalid_attribution_mode_raises_validation_error(self):
        ma_config = self.team.marketing_analytics_config
        ma_config.attribution_mode = "bogus"
        with self.assertRaises(ValidationError):
            ma_config.full_clean()
