from datetime import datetime

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import param, parameterized

from posthog.schema import ActionsNode, BreakdownFilter, DateRange, EventsNode, HogQLQueryModifiers, TrendsQuery

from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team

from products.product_analytics.backend.hogql_queries.trends.trends_query_builder import TrendsQueryBuilder


class TestRankedBreakdownGate(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=314, timezone="UTC", test_account_filters=[])
        self.query = TrendsQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            interval="day",
            series=[EventsNode(event="screen viewed", math="total")],
            breakdownFilter=BreakdownFilter(breakdown="route", breakdown_type="event", breakdown_limit=3),
            filterTestAccounts=True,
        )

    def builder(
        self, query: TrendsQuery, modifiers: HogQLQueryModifiers | None = None, team: Team | None = None
    ) -> TrendsQueryBuilder:
        assert isinstance(query.series[0], (EventsNode, ActionsNode))
        team = team or self.team
        return TrendsQueryBuilder(
            query,
            team,
            QueryDateRange(query.dateRange, team, query.interval, datetime(2024, 1, 10)),
            query.series[0],
            HogQLTimings(),
            modifiers or HogQLQueryModifiers(),
        )

    @parameterized.expand(
        [
            param("matching", True),
            param("response", True, query_updates={"response": {"results": [{"count": 5}]}}),
            param("colors", True, query_updates={"dataColorTheme": 2}),
            param("legend", True, query_updates={"trendsFilter": {"showLegend": True}}),
            param(
                "series_presentation",
                True,
                query_updates={
                    "series": [
                        EventsNode(event="screen viewed", math="total", custom_name="Visits", response={"count": 5})
                    ]
                },
            ),
            param(
                "shifted_dates",
                True,
                query_updates={"dateRange": DateRange(date_from="2024-01-02", date_to="2024-01-08")},
            ),
            param("team", False, team_updates={"id": 315}),
            param("timezone", False, team_updates={"timezone": "Pacific/Auckland"}),
            param("week_start", False, team_updates={"week_start_day": 1}),
            param("event", False, query_updates={"series": [EventsNode(event="button clicked", math="total")]}),
            param(
                "series_filter",
                False,
                query_updates={
                    "series": [
                        EventsNode(
                            event="screen viewed",
                            math="total",
                            properties=[{"type": "event", "key": "status", "operator": "exact", "value": "ok"}],
                        )
                    ]
                },
            ),
            param(
                "query_filter",
                False,
                query_updates={"properties": [{"type": "event", "key": "status", "operator": "exact", "value": "ok"}]},
            ),
            param(
                "breakdown",
                False,
                query_updates={
                    "breakdownFilter": BreakdownFilter(breakdown="category", breakdown_type="event", breakdown_limit=3)
                },
            ),
            param(
                "breakdown_limit",
                False,
                query_updates={
                    "breakdownFilter": BreakdownFilter(breakdown="route", breakdown_type="event", breakdown_limit=4)
                },
            ),
            param("interval", False, query_updates={"interval": "hour"}),
            param(
                "range_length",
                False,
                query_updates={"dateRange": DateRange(date_from="2024-01-01", date_to="2024-01-08")},
            ),
            param(
                "days_of_week",
                False,
                query_updates={"dateRange": DateRange(date_from="2024-01-01", date_to="2024-01-07", daysOfWeek=[1, 2])},
            ),
            param(
                "test_account_filters",
                False,
                team_updates={
                    "test_account_filters": [
                        {"type": "event", "key": "status", "operator": "exact", "value": "internal"}
                    ]
                },
            ),
            param("modifiers", False, modifiers=HogQLQueryModifiers(convertToProjectTimezone=True)),
            param("sampling", False, query_updates={"samplingFactor": 0.25}),
            param("unapproved", False, allowed="other-signature"),
            param("empty_allowlist", False, allowed=""),
            param("malformed_allowlist", False, malformed=True),
            param("flag_disabled", False, enabled=False),
            param(
                "range_alignment",
                False,
                query_updates={
                    "dateRange": DateRange(
                        date_from="2024-01-01T12:00:00", date_to="2024-01-08T11:59:59", explicitDate=True
                    )
                },
            ),
        ]
    )
    def test_only_approved_configurations_build_ranked_queries(
        self,
        name: str,
        ranked: bool,
        query_updates: dict[str, object] | None = None,
        team_updates: dict[str, object] | None = None,
        modifiers: HogQLQueryModifiers | None = None,
        allowed: str | None = None,
        enabled: bool = True,
        malformed: bool = False,
    ) -> None:
        signature = self.builder(self.query).ranked_breakdown_query_signature
        assert signature is not None
        query = self.query.model_dump(mode="json")
        query.update(query_updates or {})
        team = Team(**({"id": 314, "timezone": "UTC", "test_account_filters": []} | (team_updates or {})))
        configuration = (
            [signature] if malformed else allowed if allowed is not None else f" other-signature, {signature} "
        )
        builder = self.builder(TrendsQuery.model_validate(query), modifiers, team)
        with (
            patch(
                "products.product_analytics.backend.hogql_queries.trends.trends_query_builder.get_instance_setting",
                return_value=configuration,
            ),
            patch(
                "products.product_analytics.backend.hogql_queries.trends.trends_query_builder.feature_enabled_or_false",
                side_effect=lambda key, *args, **kwargs: enabled and key == "trends-breakdown-rank-before-arrays",
            ),
        ):
            sql = print_prepared_ast(builder.build_query(), HogQLContext(team_id=team.pk), "hogql")
        assert ("dense_rank()" in sql) is ranked

    def test_explicit_date_changes_the_signature_for_an_unaligned_range(self) -> None:
        query = self.query.model_copy(deep=True)
        query.dateRange = DateRange(
            date_from="2024-01-01T12:00:00", date_to="2024-01-07T23:59:59.999999", explicitDate=False
        )
        explicit_query = query.model_copy(deep=True)
        explicit_query.dateRange = DateRange(
            date_from="2024-01-01T12:00:00", date_to="2024-01-07T23:59:59.999999", explicitDate=True
        )

        assert self.builder(query).ranked_breakdown_query_signature != self.builder(
            explicit_query
        ).ranked_breakdown_query_signature

    @parameterized.expand([("action",), ("all_time",)])
    def test_configurations_without_a_stable_cheap_signature(self, kind: str) -> None:
        query = self.query.model_copy(deep=True)
        if kind == "action":
            query.series = [ActionsNode(id=123, math="total")]
        else:
            query.dateRange = DateRange(date_from="all")
        assert self.builder(query).ranked_breakdown_query_signature is None
