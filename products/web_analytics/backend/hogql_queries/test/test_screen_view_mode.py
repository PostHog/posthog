from types import SimpleNamespace
from typing import Any, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, WebAnalyticsScreenViewMode

from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import clear_locations

from products.web_analytics.backend.hogql_queries.screen_view_mode import (
    effective_screen_view_mode,
    with_screen_name_path_fallback,
)

BOTH = WebAnalyticsScreenViewMode.PAGEVIEWS_AND_SCREENS


class TestScreenViewMode(SimpleTestCase):
    @parameterized.expand(
        [
            ("nothing_set", None, None, None),
            ("team_setting", {"webAnalyticsScreenViewMode": "screens"}, None, WebAnalyticsScreenViewMode.SCREENS),
            ("invalid_team_setting_is_unset", {"webAnalyticsScreenViewMode": "not_a_mode"}, None, None),
            (
                "request_overrides_team",
                {"webAnalyticsScreenViewMode": "screens"},
                HogQLQueryModifiers(webAnalyticsScreenViewMode=WebAnalyticsScreenViewMode.PAGEVIEWS),
                WebAnalyticsScreenViewMode.PAGEVIEWS,
            ),
        ]
    )
    def test_effective_mode(
        self,
        _name: str,
        team_modifiers: Optional[dict[str, Any]],
        request_modifiers: Optional[HogQLQueryModifiers],
        expected: Optional[WebAnalyticsScreenViewMode],
    ) -> None:
        team: Any = SimpleNamespace(modifiers=team_modifiers)
        assert effective_screen_view_mode(team, request_modifiers) == expected

    @parameterized.expand(
        [
            ("unset_keeps_pathname", None, "SELECT properties.$pathname FROM events", "properties.$pathname"),
            (
                "pageviews_keeps_pathname",
                WebAnalyticsScreenViewMode.PAGEVIEWS,
                "SELECT properties.$pathname FROM events",
                "properties.$pathname",
            ),
            (
                "fallback_on_bare_field",
                BOTH,
                "SELECT properties.$pathname FROM events",
                "coalesce(nullIf(properties.$pathname, ''), properties.$screen_name)",
            ),
            (
                "fallback_on_table_qualified_field",
                BOTH,
                "SELECT events.properties.$pathname FROM events",
                "coalesce(nullIf(events.properties.$pathname, ''), events.properties.$screen_name)",
            ),
            (
                "person_property_untouched",
                BOTH,
                "SELECT person.properties.$pathname FROM events",
                "person.properties.$pathname",
            ),
        ]
    )
    def test_pathname_fallback_rewrite(
        self, _name: str, mode: Optional[WebAnalyticsScreenViewMode], query: str, expected_select: str
    ) -> None:
        rewritten = with_screen_name_path_fallback(parse_select(query), mode)
        assert clear_locations(rewritten) == clear_locations(parse_select(f"SELECT {expected_select} FROM events"))
