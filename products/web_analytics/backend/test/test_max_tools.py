from posthog.test.base import APIBaseTest

from posthog.schema import (
    CompareFilter,
    EventPropertyFilter,
    PropertyOperator,
    SessionPropertyFilter,
    WebAnalyticsAssistantFilters,
)

from ..max_tools import WebAnalyticsFilterOptionsToolkit


class TestWebAnalyticsFilterOptionsToolkit(APIBaseTest):
    def test_toolkit_initialization(self):
        toolkit = WebAnalyticsFilterOptionsToolkit(self.team, self.user)
        assert toolkit is not None

        tools = toolkit.get_tools()
        tool_names = [tool.__name__ for tool in tools]

        assert "final_answer" in tool_names
        assert "retrieve_web_analytics_property_values" in tool_names
        assert "ask_user_for_help" in tool_names


class TestWebAnalyticsAssistantFilters(APIBaseTest):
    def test_filters_validation(self):
        filters = WebAnalyticsAssistantFilters(
            date_from="-7d",
            date_to=None,
            doPathCleaning=True,
            compareFilter=CompareFilter(compare=True, compare_to="previous"),
            properties=[
                EventPropertyFilter(
                    key="$geoip_country_code",
                    type="event",
                    value=["FR"],
                    operator=PropertyOperator.EXACT,
                ),
            ],
        )

        assert filters.date_from == "-7d"
        assert filters.date_to is None
        assert filters.doPathCleaning is True
        assert filters.compareFilter is not None
        assert filters.compareFilter.compare is True
        assert len(filters.properties) == 1
        assert filters.properties[0].key == "$geoip_country_code"

    def test_filters_with_multiple_properties(self):
        filters = WebAnalyticsAssistantFilters(
            date_from="-30d",
            date_to=None,
            doPathCleaning=False,
            compareFilter=None,
            properties=[
                EventPropertyFilter(
                    key="$browser",
                    type="event",
                    value=["Chrome", "Firefox"],
                    operator=PropertyOperator.EXACT,
                ),
                EventPropertyFilter(
                    key="$device_type",
                    type="event",
                    value=["Mobile"],
                    operator=PropertyOperator.EXACT,
                ),
            ],
        )

        assert len(filters.properties) == 2
        assert filters.doPathCleaning is False
        assert filters.compareFilter is None

    def test_filters_with_is_bounce_session_property(self):
        """Test that $is_bounce session property is handled correctly with 0/1 values."""
        filters = WebAnalyticsAssistantFilters(
            date_from="-7d",
            date_to=None,
            doPathCleaning=False,
            compareFilter=None,
            properties=[
                SessionPropertyFilter(
                    key="$is_bounce",
                    type="session",
                    value=["1"],
                    operator=PropertyOperator.EXACT,
                ),
            ],
        )

        assert len(filters.properties) == 1
        assert filters.properties[0].key == "$is_bounce"
        assert filters.properties[0].type == "session"
        assert filters.properties[0].value == ["1"]

    def test_filters_with_session_duration_property(self):
        """Test that $session_duration numeric session property is handled correctly."""
        filters = WebAnalyticsAssistantFilters(
            date_from="-30d",
            date_to=None,
            doPathCleaning=True,
            compareFilter=None,
            properties=[
                SessionPropertyFilter(
                    key="$session_duration",
                    type="session",
                    value="120",
                    operator=PropertyOperator.GT,
                ),
            ],
        )

        assert len(filters.properties) == 1
        assert filters.properties[0].key == "$session_duration"
        assert filters.properties[0].type == "session"
        assert filters.properties[0].value == "120"
        assert filters.properties[0].operator == PropertyOperator.GT

    def test_filters_with_mixed_session_and_event_properties(self):
        """Test filters with both session and event properties."""
        filters = WebAnalyticsAssistantFilters(
            date_from="-14d",
            date_to=None,
            doPathCleaning=True,
            compareFilter=None,
            properties=[
                SessionPropertyFilter(
                    key="$is_bounce",
                    type="session",
                    value=["0"],
                    operator=PropertyOperator.EXACT,
                ),
                SessionPropertyFilter(
                    key="$session_duration",
                    type="session",
                    value="60",
                    operator=PropertyOperator.GTE,
                ),
                EventPropertyFilter(
                    key="$device_type",
                    type="event",
                    value=["Desktop"],
                    operator=PropertyOperator.EXACT,
                ),
            ],
        )

        assert len(filters.properties) == 3
        session_props = [p for p in filters.properties if p.type == "session"]
        event_props = [p for p in filters.properties if p.type == "event"]
        assert len(session_props) == 2
        assert len(event_props) == 1
