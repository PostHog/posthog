from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.web_analytics.backend.hogql_queries.cookieless_flag import resolve_cookieless_traffic_is_regular_modifier

IS_CLOUD = "products.web_analytics.backend.hogql_queries.cookieless_flag.is_cloud"
FEATURE_ENABLED = "posthoganalytics.feature_enabled"


class TestResolveCookielessTrafficIsRegularModifier:
    @parameterized.expand(
        [
            ("flags_on", True),
            ("flags_off", False),
            ("flags_unavailable", None),
        ]
    )
    def test_cloud_default_does_not_depend_on_local_flag_state(self, _name, flag_value):
        with patch(IS_CLOUD, return_value=True), patch(FEATURE_ENABLED, return_value=flag_value):
            assert resolve_cookieless_traffic_is_regular_modifier(MagicMock(), None) is True

    @parameterized.expand([("opted in", True), ("opted out", False)])
    def test_an_explicit_team_setting_wins(self, _name, current):
        with patch(IS_CLOUD, return_value=True):
            assert resolve_cookieless_traffic_is_regular_modifier(MagicMock(), current) is current

    def test_self_hosted_keeps_the_legacy_default(self):
        with patch(IS_CLOUD, return_value=False):
            assert resolve_cookieless_traffic_is_regular_modifier(MagicMock(), None) is None
