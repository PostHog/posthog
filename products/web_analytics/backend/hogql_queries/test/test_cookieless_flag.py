from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.web_analytics.backend.hogql_queries.cookieless_flag import resolve_cookieless_traffic_is_regular_modifier

IS_CLOUD = "products.web_analytics.backend.hogql_queries.cookieless_flag.is_cloud"
FEATURE_ENABLED = "posthoganalytics.feature_enabled"
FLAG_LOGGER = "products.web_analytics.backend.hogql_queries.first_pageview_flag.logger"


def _team() -> MagicMock:
    team = MagicMock()
    team.uuid = "team-uuid"
    team.organization_id = "org-uuid"
    team.id = 1
    team.pk = 1
    return team


class TestResolveCookielessTrafficIsRegularModifier:
    @parameterized.expand([("on", True, True), ("off", False, None), ("missing", None, None)])
    def test_the_flag_decides_on_cloud_without_logging(self, _name, flag_value, expected):
        with (
            patch(IS_CLOUD, return_value=True),
            patch(FEATURE_ENABLED, return_value=flag_value) as feature_enabled,
            patch(FLAG_LOGGER) as logger,
        ):
            assert resolve_cookieless_traffic_is_regular_modifier(_team(), None) is expected

        feature_enabled.assert_called_once()
        logger.warning.assert_not_called()

    @parameterized.expand([("opted in", True), ("opted out", False)])
    def test_an_explicit_team_setting_skips_the_flag(self, _name, current):
        with patch(IS_CLOUD, return_value=True), patch(FEATURE_ENABLED) as feature_enabled:
            assert resolve_cookieless_traffic_is_regular_modifier(_team(), current) is current

        feature_enabled.assert_not_called()

    def test_self_hosted_never_consults_the_flag(self):
        with patch(IS_CLOUD, return_value=False), patch(FEATURE_ENABLED) as feature_enabled:
            assert resolve_cookieless_traffic_is_regular_modifier(_team(), None) is None

        feature_enabled.assert_not_called()
