from posthog.test.base import APIBaseTest

from posthog.schema import CompareFilter, EventPropertyFilter, PropertyOperator, WebAnalyticsAssistantFilters

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
