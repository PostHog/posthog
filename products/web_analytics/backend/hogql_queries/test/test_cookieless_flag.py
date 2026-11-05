from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.team.team import CookielessServerHashMode

from products.web_analytics.backend.hogql_queries.cookieless_flag import resolve_cookieless_traffic_is_regular_modifier

IS_CLOUD = "products.web_analytics.backend.hogql_queries.cookieless_flag.is_cloud"
FEATURE_ENABLED = "posthoganalytics.feature_enabled"


def _team(cookieless_mode: CookielessServerHashMode | None = CookielessServerHashMode.STATEFUL) -> MagicMock:
    return MagicMock(cookieless_server_hash_mode=cookieless_mode)


class TestResolveCookielessTrafficIsRegularModifier:
    @parameterized.expand(
        [
            ("flags_on", True),
            ("flags_off", False),
            ("flags_unavailable", None),
        ]
    )
    def test_cloud_default_does_not_depend_on_local_flag_state(self, _name, flag_value):
        with patch(IS_CLOUD, return_value=True), patch(FEATURE_ENABLED, return_value=flag_value) as feature_enabled:
            assert resolve_cookieless_traffic_is_regular_modifier(_team(), None) is True

        feature_enabled.assert_not_called()

    @parameterized.expand([("opted in", True), ("opted out", False)])
    def test_an_explicit_team_setting_wins(self, _name, current):
        with patch(IS_CLOUD, return_value=True):
            assert resolve_cookieless_traffic_is_regular_modifier(_team(), current) is current

    @parameterized.expand(
        [
            ("disabled_default", CookielessServerHashMode.DISABLED, None),
            ("disabled_opted_in", CookielessServerHashMode.DISABLED, True),
            ("unset_default", None, None),
        ]
    )
    def test_a_team_without_cookieless_never_gets_the_exemption(self, _name, cookieless_mode, current):
        with patch(IS_CLOUD, return_value=True):
            assert resolve_cookieless_traffic_is_regular_modifier(_team(cookieless_mode), current) is False

    def test_stateless_mode_counts_as_cookieless(self):
        with patch(IS_CLOUD, return_value=True):
            assert (
                resolve_cookieless_traffic_is_regular_modifier(_team(CookielessServerHashMode.STATELESS), None) is True
            )

    def test_self_hosted_keeps_the_legacy_default(self):
        with patch(IS_CLOUD, return_value=False):
            assert resolve_cookieless_traffic_is_regular_modifier(_team(), None) is None
