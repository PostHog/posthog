from datetime import UTC, date, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers, HogQLVariable, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team

from products.actions.backend.facade.testing import create_action
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.cohorts.backend.models.cohort import Cohort
from products.product_analytics.backend.facade.contracts import ClosedSqlSeriesValues, SeriesValuesUnavailable
from products.product_analytics.backend.hogql_queries.trends.sql_series_values_precompute import (
    _Bucket,
    _bucket,
    _compiled_read_refusal,
    _insert_query,
    _SqlShape,
    _Where,
    _where,
    closed_sql_series_values,
)

_NOW = "2024-01-15T12:00:00Z"
_MODULE = "products.product_analytics.backend.hogql_queries.trends.sql_series_values_precompute"

_DAILY_COUNT = (
    "SELECT toStartOfDay(timestamp) AS day, count() AS value FROM events "
    "WHERE timestamp >= now() - INTERVAL 7 DAY AND event = 'signed_up' GROUP BY day ORDER BY day"
)
_LATER_ALIAS = (
    "SELECT toStartOfDay(timestamp) AS day, count() AS value, max(issue_status = 'x'), event AS issue_status "
    "FROM events WHERE timestamp >= now() - INTERVAL 7 DAY GROUP BY day"
)
_OVERRIDES = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS


def _instant(bucket: date | datetime) -> datetime:
    if isinstance(bucket, datetime):
        return bucket.astimezone(UTC)
    return datetime(bucket.year, bucket.month, bucket.day, tzinfo=UTC)


_EVENTS = (
    (8, 5, 0, "a"),
    (6, 5, 0, "a"),
    (5, 15, 0, "a"),
    (5, 15, 40, "a"),
    (5, 16, 10, "b"),
    (3, 23, 30, "c"),
    (1, 3, 0, "a"),
    (1, 3, 20, "b"),
    (1, 23, 59, "a"),
)


@override_settings(IN_UNIT_TESTING=True)
class TestSqlSeriesValuesPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        sync_execute("SYSTEM STOP TTL MERGES sharded_series_values_preaggregated")
        self.addCleanup(sync_execute, "SYSTEM START TTL MERGES sharded_series_values_preaggregated")

    def _seed(self, today: datetime) -> None:
        for days_ago, hour, minute, distinct_id in _EVENTS:
            timestamp = today - timedelta(days=days_ago) + timedelta(hours=hour, minutes=minute)
            _create_event(team=self.team, event="signed_up", distinct_id=distinct_id, timestamp=timestamp)
        _create_event(team=self.team, event="other", distinct_id="a", timestamp=today - timedelta(hours=14))
        flush_persons_and_events()

    def _closed(self, query: HogQLQuery, value_column: str = "value") -> ClosedSqlSeriesValues:
        closed = closed_sql_series_values(self.team, query, value_column=value_column, run_inserts=True)
        assert isinstance(closed, ClosedSqlSeriesValues), closed
        return closed

    @parameterized.expand(
        [
            ("count_by_day", _DAILY_COUNT, "value"),
            (
                "count_by_hour",
                "SELECT toStartOfHour(timestamp) AS hour, count(*) AS value FROM events "
                "WHERE timestamp >= now() - INTERVAL 7 DAY AND timestamp < now() AND event = 'signed_up' GROUP BY hour",
                "value",
            ),
            (
                "distinct_users_by_utc_day",
                "SELECT toStartOfDay(timestamp, 'UTC') AS day, uniq(distinct_id) AS users, 'all' AS label "
                "FROM events WHERE timestamp >= subtractDays(today(), 7) GROUP BY day ORDER BY day DESC LIMIT 5",
                "users",
            ),
            (
                "distinct_users_by_date",
                "SELECT toDate(timestamp) AS day, count(DISTINCT distinct_id) AS users FROM events "
                "WHERE timestamp > now() - INTERVAL 1 WEEK GROUP BY day",
                "users",
            ),
        ]
    )
    def test_matches_the_live_query_for_every_closed_bucket(self, _name: str, sql: str, value_column: str) -> None:
        clickhouse_now = sync_execute("SELECT now64(6, 'UTC')")[0][0]
        self._seed(clickhouse_now.replace(hour=0, minute=0, second=0, microsecond=0))
        query = HogQLQuery(query=sql)
        saved = query.model_copy(deep=True)

        with time_machine.travel(clickhouse_now, tick=False):
            closed = self._closed(query, value_column)

        live = execute_hogql_query(sql, self.team)
        assert live.columns is not None
        bucket_index = live.columns.index(closed.bucket_column)
        value_index = live.columns.index(value_column)
        first_live = min(_instant(row[bucket_index]) for row in live.results)
        expected = {
            _instant(row[bucket_index]): float(row[value_index])
            for row in live.results
            if first_live < _instant(row[bucket_index]) < closed.closed_before
        }
        assert len(expected) >= 3
        assert {bucket: value for bucket, value in closed.values.items() if bucket > first_live} == expected
        assert query == saved

    def test_later_checks_reuse_the_stored_days(self) -> None:
        self._seed(datetime(2024, 1, 15, tzinfo=UTC))
        with time_machine.travel(_NOW, tick=False):
            first = self._closed(HogQLQuery(query=_DAILY_COUNT))
        jobs = set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True))
        with time_machine.travel("2024-01-15T15:00:00Z", tick=False):
            second = self._closed(HogQLQuery(query=_DAILY_COUNT.replace("7 DAY", "5 DAY")))

        assert first.freshly_built and not second.freshly_built
        assert set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True)) == jobs
        assert first.values == {
            datetime(2024, 1, day, tzinfo=UTC): value for day, value in ((9, 1.0), (10, 3.0), (12, 1.0), (14, 3.0))
        }
        assert second.values.items() <= first.values.items()


@time_machine.travel(_NOW, tick=False)
class TestSqlSeriesValuesRefusals(SimpleTestCase):
    @parameterized.expand(
        [
            ("connection", HogQLQuery(query=_DAILY_COUNT, connectionId="c1"), "value", "UTC"),
            ("connection", HogQLQuery(query=_DAILY_COUNT, sendRawQuery=True), "value", "UTC"),
            (
                "variables",
                HogQLQuery(query=_DAILY_COUNT, variables={"v": HogQLVariable(variableId="v", code_name="v")}),
                "value",
                "UTC",
            ),
            ("variables", HogQLQuery(query=_DAILY_COUNT.replace("'signed_up'", "{variables.event}")), "value", "UTC"),
            (
                "filters_placeholder",
                HogQLQuery(query=_DAILY_COUNT.replace("event =", "{filters} AND event =")),
                "value",
                "UTC",
            ),
            (
                "modifiers",
                HogQLQuery(
                    query=_DAILY_COUNT, modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
                ),
                "value",
                "UTC",
            ),
            ("parse_error", HogQLQuery(query="SELECT FROM WHERE"), "value", "UTC"),
            ("set_operation", HogQLQuery(query=f"{_DAILY_COUNT} UNION ALL {_DAILY_COUNT}"), "value", "UTC"),
            (
                "source",
                HogQLQuery(
                    query=_DAILY_COUNT.replace("FROM events", "FROM events JOIN persons ON persons.id = person_id")
                ),
                "value",
                "UTC",
            ),
            (
                "source",
                HogQLQuery(query=_DAILY_COUNT.replace("FROM events", "FROM (SELECT * FROM events)")),
                "value",
                "UTC",
            ),
            (
                "source",
                HogQLQuery(query=_DAILY_COUNT.replace("event = 'signed_up'", "person.properties.plan = 'pro'")),
                "value",
                "UTC",
            ),
            (
                "source",
                HogQLQuery(
                    query=_DAILY_COUNT.replace(
                        "event = 'signed_up'", "distinct_id IN (SELECT distinct_id FROM person_distinct_ids)"
                    )
                ),
                "value",
                "UTC",
            ),
            (
                "source",
                HogQLQuery(
                    query=_DAILY_COUNT.replace("count() AS value", "count() + (SELECT count() FROM persons) AS value")
                ),
                "value",
                "UTC",
            ),
            (
                "source",
                HogQLQuery(query=_DAILY_COUNT.replace("event = 'signed_up'", "person_id IN COHORT 5")),
                "value",
                "UTC",
            ),
            *(
                ("source", HogQLQuery(query=_DAILY_COUNT.replace("event = 'signed_up'", condition)), "value", "UTC")
                for condition in (
                    "poe.revenue_analytics.revenue > 0",
                    "crm_account.plan = 'pro'",
                    "matchesAction(1)",
                    "distinct_id IN person_distinct_ids",
                    "issue_status = 'active'",
                    "arrayExists(issue_status -> 1, [1]) AND issue_status = 'active'",
                    "arrayExists(x -> (x AS issue_status) = 1, [1]) AND issue_status = 'active'",
                    "issue_status = 'active' AND (event AS issue_status) != ''",
                )
            ),
            (
                "source",
                HogQLQuery(
                    query=_DAILY_COUNT.replace("count() AS value", "count() AS value, issue_status AS issue_status")
                ),
                "value",
                "UTC",
            ),
            ("group_by", HogQLQuery(query=_DAILY_COUNT.replace("GROUP BY day", "GROUP BY day, event")), "value", "UTC"),
            ("bucket", HogQLQuery(query=_DAILY_COUNT.replace("toStartOfDay", "toStartOfWeek")), "value", "UTC"),
            ("order_by", HogQLQuery(query=_DAILY_COUNT.replace("ORDER BY day", "ORDER BY value")), "value", "UTC"),
            ("limit", HogQLQuery(query=f"{_DAILY_COUNT} LIMIT 5 OFFSET 2"), "value", "UTC"),
            (
                "window",
                HogQLQuery(query=_DAILY_COUNT.replace("now() - INTERVAL 7 DAY", "'2024-01-01'")),
                "value",
                "UTC",
            ),
            ("value_column", HogQLQuery(query=_DAILY_COUNT), "day", "UTC"),
            ("value_column", HogQLQuery(query=_DAILY_COUNT), "missing", "UTC"),
            (
                "ineligible",
                HogQLQuery(query=_DAILY_COUNT.replace("ORDER BY", "HAVING count() > 1 ORDER BY")),
                "value",
                "UTC",
            ),
            (
                "nondeterministic",
                HogQLQuery(query=_DAILY_COUNT.replace("event = 'signed_up'", "properties.seen_at < now()")),
                "value",
                "UTC",
            ),
            ("nothing_closed", HogQLQuery(query=_DAILY_COUNT.replace("7 DAY", "1 HOUR")), "value", "UTC"),
            ("date_range_too_long", HogQLQuery(query=_DAILY_COUNT.replace("7 DAY", "2 YEAR")), "value", "UTC"),
            ("timezone", HogQLQuery(query=_DAILY_COUNT), "value", "America/Los_Angeles"),
            (
                "timezone",
                HogQLQuery(query=_DAILY_COUNT.replace("toStartOfDay(timestamp)", "toStartOfHour(timestamp)")),
                "value",
                "Asia/Kolkata",
            ),
            (
                "dst_transition",
                HogQLQuery(
                    query=_DAILY_COUNT.replace("toStartOfDay(timestamp)", "toStartOfHour(timestamp)").replace(
                        "7 DAY", "3 MONTH"
                    )
                ),
                "value",
                "America/New_York",
            ),
        ]
    )
    def test_refuses_unsupported_queries(
        self, reason: str, query: HogQLQuery, value_column: str, timezone: str
    ) -> None:
        with (
            patch(f"{_MODULE}.team_has_property_access_rules", return_value=False),
            patch(f"{_MODULE}.ensure_precomputed") as ensure,
        ):
            result = closed_sql_series_values(
                Team(timezone=timezone), query, value_column=value_column, run_inserts=True
            )

        assert result == SeriesValuesUnavailable(reason=reason)
        ensure.assert_not_called()

    def test_refuses_teams_with_property_access_rules(self) -> None:
        with (
            patch(f"{_MODULE}.team_has_property_access_rules", return_value=True),
            patch(f"{_MODULE}.ensure_precomputed") as ensure,
        ):
            result = closed_sql_series_values(
                Team(timezone="UTC"), HogQLQuery(query=_DAILY_COUNT), value_column="value", run_inserts=True
            )

        assert result == SeriesValuesUnavailable(reason="property_access_rules")
        ensure.assert_not_called()


def _with(condition: str) -> str:
    return _DAILY_COUNT.replace("event = 'signed_up'", condition)


class TestCompiledReadRefusal(APIBaseTest):
    def _refusal(self, sql: str, mode: PersonsOnEventsMode = _OVERRIDES) -> str | None:
        select = parse_select(sql)
        assert isinstance(select, ast.SelectQuery) and select.select_from is not None
        bucket, where = _bucket(select), _where(select)
        assert isinstance(bucket, _Bucket) and isinstance(where, _Where)
        shape = _SqlShape(select=select, bucket_alias=bucket.alias.alias, hourly=False, utc_bucket=False, where=where)
        modifiers = create_default_modifiers_for_team(self.team)
        modifiers.personsOnEventsMode = mode
        database = Database.create_for(team=self.team, modifiers=modifiers, bypass_warehouse_access_control=True)
        return _compiled_read_refusal(
            _insert_query(shape, "value"),
            select.select_from.alias,
            self.team,
            database,
            modifiers,
            (datetime(2024, 1, 8, tzinfo=UTC), datetime(2024, 1, 15, tzinfo=UTC)),
        )

    @parameterized.expand(
        [
            ("plain", _DAILY_COUNT),
            ("properties", _with("properties.plan = 'pro' AND poe.properties.plan = 'pro'")),
            ("person_id", _DAILY_COUNT.replace("count()", "uniq(person_id)")),
            (
                "aliased_person_id",
                _DAILY_COUNT.replace("count()", "uniq(e.person_id)").replace("events", "events AS e"),
            ),
            ("lambda", _with("arrayExists(x -> x = event, ['signed_up'])")),
            ("virtual_field", _with("$virt_traffic_type = 'x'")),
        ]
    )
    def test_accepts_queries_that_compile_to_events_reads(self, _name: str, sql: str) -> None:
        assert self._refusal(sql) is None

    @parameterized.expand(
        [
            ("later_alias", _LATER_ALIAS, _OVERRIDES),
            (
                "self_alias",
                _DAILY_COUNT.replace("count() AS value", "count() AS value, issue_status AS issue_status"),
                _OVERRIDES,
            ),
            ("expression_field", _with("issue_status = 'active'"), _OVERRIDES),
            ("lambda_shadow", _with("arrayExists(issue_status -> 1, [1]) AND issue_status = 'active'"), _OVERRIDES),
            (
                "lambda_alias",
                _with("arrayExists(x -> (x AS issue_status) = 1, [1]) AND issue_status = 'active'"),
                _OVERRIDES,
            ),
            ("where_alias", _with("issue_status = 'active' AND (event AS issue_status) != ''"), _OVERRIDES),
            (
                "join",
                _DAILY_COUNT.replace("FROM events", "FROM events JOIN persons ON persons.id = person_id"),
                _OVERRIDES,
            ),
            (
                "person_properties",
                _with("person.properties.plan = 'pro'"),
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            ),
            (
                "person_id_without_overrides",
                _DAILY_COUNT.replace("count()", "uniq(person_id)"),
                PersonsOnEventsMode.DISABLED,
            ),
            ("in_subquery", _with("distinct_id IN (SELECT distinct_id FROM person_distinct_ids)"), _OVERRIDES),
            (
                "in_overrides",
                _with("distinct_id IN (SELECT distinct_id FROM person_distinct_id_overrides)"),
                _OVERRIDES,
            ),
            (
                "overrides_join",
                _DAILY_COUNT.replace(
                    "FROM events",
                    "FROM events LEFT JOIN person_distinct_id_overrides AS o ON o.distinct_id = distinct_id",
                ),
                _OVERRIDES,
            ),
            (
                "scalar_subquery",
                _DAILY_COUNT.replace("count() AS value", "count() + (SELECT count() FROM persons) AS value"),
                _OVERRIDES,
            ),
            ("table_function", _with("toInt(event) IN (SELECT number FROM numbers(10))"), _OVERRIDES),
            ("in_table", _with("distinct_id IN person_distinct_ids"), _OVERRIDES),
            ("revenue", _with("poe.revenue_analytics.revenue > 0"), _OVERRIDES),
            ("warehouse_join", _with("crm_account.plan = 'pro'"), _OVERRIDES),
            ("sessions", _with("session.$session_duration > 1"), _OVERRIDES),
            ("dictionary", _with("lookupDomainType(properties.$referring_domain) = 'x'"), _OVERRIDES),
            ("in_cohort", _with("person_id IN COHORT {cohort}"), _OVERRIDES),
            ("cohort_call", _with("person_id IN cohort({cohort})"), _OVERRIDES),
            ("action", _with("matchesAction({action})"), _OVERRIDES),
        ]
    )
    def test_refuses_queries_that_compile_to_other_reads(self, _name: str, sql: str, mode: PersonsOnEventsMode) -> None:
        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
        action = create_action(team=self.team, name="signed up", steps_json=[{"event": "signed_up"}])

        assert self._refusal(sql.format(cohort=cohort.pk, action=action.id), mode) == "source"

    @parameterized.expand([(_LATER_ALIAS,), (_with("issue_status = 'active' AND (event AS issue_status) != ''"),)])
    @time_machine.travel(_NOW, tick=False)
    def test_refuses_before_building(self, sql: str) -> None:
        with patch(f"{_MODULE}.ensure_precomputed") as ensure:
            result = closed_sql_series_values(self.team, HogQLQuery(query=sql), value_column="value", run_inserts=True)

        assert result == SeriesValuesUnavailable(reason="source")
        ensure.assert_not_called()
