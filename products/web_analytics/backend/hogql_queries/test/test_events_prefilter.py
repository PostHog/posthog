from posthog.test.base import APIBaseTest, ClickhouseTestMixin, also_test_with_materialized_columns, materialized
from unittest.mock import patch

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_ast_for_printing, print_prepared_ast

from products.web_analytics.backend.hogql_queries.events_prefilter import EventsPrefilterTransformer
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner


class TestEventsPrefilterTransformer(ClickhouseTestMixin, APIBaseTest):
    def _run_prefiltered_query(self, **query_kwargs):
        query_kwargs.setdefault("properties", [])
        query_kwargs.setdefault("breakdownBy", WebStatsBreakdown.PAGE)
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            **query_kwargs,
        )
        with patch(
            "products.web_analytics.backend.hogql_queries.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            assert runner.paginator.response is not None
            return runner.paginator.response.clickhouse or ""

    def test_bounce_query_wraps_from_events(self):
        sql = self._run_prefiltered_query(includeBounceRate=True)

        assert "toDate(events.timestamp)" in sql
        assert sql.count("toDate(events.timestamp)") >= 2  # at least one FROM events wrapped

    def test_avg_time_query_wraps_from_events(self):
        sql = self._run_prefiltered_query(includeAvgTimeOnPage=True)

        assert "toDate(events.timestamp)" in sql

    def test_prefilter_includes_team_id(self):
        sql = self._run_prefiltered_query(includeBounceRate=True)

        assert f"equals(events.team_id, {self.team.pk})" in sql

    def test_prefilter_date_bounds_have_buffer(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "products.web_analytics.backend.hogql_queries.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            date_from, date_to = runner._events_prefilter_date_bounds()

        # Date range is Jan 1-31, buffer is ±1 day
        assert date_from == "2023-12-31"
        assert date_to == "2024-02-01"

    def test_prefilter_with_event_filter(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[
                EventPropertyFilter(
                    key="$geoip_city_name",
                    operator=PropertyOperator.EXACT,
                    value=["Pretoria"],
                )
            ],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "products.web_analytics.backend.hogql_queries.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            assert runner.paginator.response is not None
            sql = runner.paginator.response.clickhouse or ""

        assert "toDate(events.timestamp)" in sql

    def test_non_prefiltered_team_unchanged(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "products.web_analytics.backend.hogql_queries.stats_table.is_web_analytics_events_prefilter_team",
            return_value=False,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            assert runner.paginator.response is not None
            sql = runner.paginator.response.clickhouse or ""

        assert "toDate(events.timestamp)" not in sql

    def test_main_query_without_bounce_not_affected(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
        )
        with patch(
            "products.web_analytics.backend.hogql_queries.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            assert runner.paginator.response is not None
            sql = runner.paginator.response.clickhouse or ""

        # Non-bounce queries also get wrapped since they go through the same _calculate path
        assert "toDate(events.timestamp)" in sql

    @also_test_with_materialized_columns(
        event_properties=["$pathname", "$geoip_city_name"],
        verify_no_jsonextract=False,
    )
    def test_bounce_with_geo_filter(self):
        sql = self._run_prefiltered_query(
            includeBounceRate=True,
            properties=[
                EventPropertyFilter(
                    key="$geoip_city_name",
                    operator=PropertyOperator.EXACT,
                    value=["Pretoria"],
                )
            ],
        )

        assert "toDate(events.timestamp)" in sql
        assert sql.count("toDate(events.timestamp)") >= 2

    def test_bounce_with_non_utc_timezone(self):
        self.team.timezone = "Europe/Berlin"
        self.team.save()

        sql = self._run_prefiltered_query(includeBounceRate=True)

        assert "toDate(events.timestamp)" in sql
        assert sql.count("toDate(events.timestamp)") >= 2

    def test_bounce_with_unmaterialized_property_filter(self):
        sql = self._run_prefiltered_query(
            includeBounceRate=True,
            properties=[
                EventPropertyFilter(
                    key="customProperty",
                    operator=PropertyOperator.EXACT,
                    value=["1"],
                )
            ],
        )

        assert "toDate(events.timestamp)" in sql
        # properties blob must be in the subquery for JSONExtractRaw
        assert "events.properties" in sql
        assert "JSONExtractRaw(events.properties," in sql

    def test_bounce_with_materialized_event_property_filter(self):
        # Property resolution rewrites a materialized property read to a synthetic mat_* column the HogQL schema
        # doesn't know about; the prefilter subquery must still SELECT that column or the outer query fails with
        # UNKNOWN_IDENTIFIER. Executes against ClickHouse, so a missing column fails the query itself.
        with materialized("events", "customProperty"):
            sql = self._run_prefiltered_query(
                includeBounceRate=True,
                properties=[
                    EventPropertyFilter(
                        key="customProperty",
                        operator=PropertyOperator.EXACT,
                        value=["1"],
                    )
                ],
            )

        assert "mat_customProperty" in sql
        assert sql.count("mat_customProperty") >= 2, (
            "subquery must SELECT the materialized column the outer query reads"
        )

    def test_host_filter_with_path_cleaning_and_host_prepend(self):
        # The dashboard's domain dropdown: a materialized $host property filter combined
        # with includeHost + doPathCleaning. The host-prepended breakdown reads $host in
        # a scope the prefilter wrapper must still satisfy; prod failed with code 47
        # (Identifier 'events.mat_$host' cannot be resolved from subquery with name events).
        self.team.path_cleaning_filters = [
            {"regex": "/person/[^/#]+", "alias": "/person/<id>", "order": 0},
            {"regex": "/insights/[A-Za-z0-9]+", "alias": "/insights/<id>", "order": 1},
        ]
        self.team.test_account_filters = [{"key": "$ip", "type": "event", "value": "127.0.0.1", "operator": "is_not"}]
        self.team.save()
        with materialized("events", "$host"), materialized("events", "$ip"):
            sql = self._run_prefiltered_query(
                includeBounceRate=True,
                includeHost=True,
                doPathCleaning=True,
                filterTestAccounts=True,
                compareFilter=CompareFilter(compare=True),
                properties=[
                    EventPropertyFilter(
                        key="$host",
                        operator=PropertyOperator.EXACT,
                        value=["posthog.com"],
                    )
                ],
            )

        assert "toDate(events.timestamp)" in sql
        # Both wrapped scopes (counts + bounce) filter on $host, so both prefilter
        # subqueries must project the materialized column.
        assert sql.count("mat_$host") >= 4

    def test_deep_key_read_off_materialized_column_kept_in_subquery(self):
        # A deep read (properties.customProperty.bar) through a materialized column becomes a JSON extract over the
        # synthetic mat_* column; the transformer must keep that column in the prefilter subquery.
        with materialized("events", "customProperty"):
            context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
            node = parse_select("SELECT count() FROM events WHERE properties.customProperty.bar = 'x'")
            prepared = prepare_ast_for_printing(node, context=context, dialect="clickhouse", stack=[])
            assert prepared is not None
            transformer = EventsPrefilterTransformer(team_id=self.team.pk, date_from="2024-01-01", date_to="2024-01-02")
            try:
                transformer.visit(prepared)
                assert transformer.wraps_applied == 1
                sql = print_prepared_ast(prepared, context=context, dialect="clickhouse")
            finally:
                transformer.cleanup_temp_schema_fields()

        assert sql.count("mat_customProperty") >= 2, (
            "subquery must SELECT the materialized column the outer query reads"
        )

    @also_test_with_materialized_columns(
        person_properties=["email"],
        verify_no_jsonextract=False,
    )
    def test_bounce_with_person_property_filter(self):
        from posthog.schema import PersonsOnEventsMode

        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS}
        self.team.save()

        sql = self._run_prefiltered_query(
            includeBounceRate=True,
            properties=[
                PersonPropertyFilter(
                    key="email",
                    operator=PropertyOperator.IS_NOT,
                    value=["test@example.com"],
                )
            ],
        )

        assert "toDate(events.timestamp)" in sql
        # When materialized with PoE, mat_pp_email must be in the prefilter subquery
        # SELECT — if missing, the query above would fail with UNKNOWN_IDENTIFIER.
        # Also verify it appears in the generated SQL for the materialized case.
        if "mat_pp_email" in sql:
            assert sql.count("mat_pp_email") >= 2, (
                "mat_pp_email should appear in both the subquery SELECT and outer WHERE"
            )

    def test_initial_page_breakdown_with_bounce(self):
        sql = self._run_prefiltered_query(
            includeBounceRate=True,
            breakdownBy=WebStatsBreakdown.INITIAL_PAGE,
        )

        assert "toDate(events.timestamp)" in sql
