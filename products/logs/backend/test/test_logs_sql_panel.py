import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import HogQLQuery, HogQLQueryModifiers, PropertyGroupsMode

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

OPTIMIZED = HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.OPTIMIZED)


class TestLogsSqlPanel(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            # logical key (what a user writes) — reads the `attributes` Map ALIAS via map subscript
            ("dot_logical", "SELECT count() FROM logs WHERE attributes.tennis_session_id = 'x'"),
            ("subscript_logical", "SELECT count() FROM logs WHERE attributes['tennis_session_id'] = 'x'"),
            ("has_logical", "SELECT count() FROM logs WHERE has(attributes, 'tennis_session_id')"),
            ("resource_logical", "SELECT count() FROM logs WHERE resource_attributes['k8s.namespace'] = 'x'"),
            # suffixed key (internal filter form) — routed to the typed `attributes_map_str` via property groups
            ("dot_suffixed", "SELECT count() FROM logs WHERE attributes.`tennis_session_id__str` = 'x'"),
        ]
    )
    def test_attribute_access_never_uses_json_extract(self, _name, query):
        # Logs attributes are physical ClickHouse Map columns, not JSON blobs. Every access form must compile to a
        # map read (subscript or property-group column) — JSONExtract is illegal on a Map and errors at execution.
        runner = HogQLQueryRunner(query=HogQLQuery(query=query), team=self.team)
        response = runner.calculate()
        sql = response.clickhouse or ""
        assert "JSONExtract" not in sql

    @parameterized.expand(
        [
            ("dot", "SELECT attributes.tennis_session_id FROM logs"),
            ("subscript", "SELECT attributes['tennis_session_id'] FROM logs"),
            ("dot_in_where", "SELECT count() FROM logs WHERE attributes.tennis_session_id = 'x'"),
        ]
    )
    def test_bare_attribute_key_reads_the_physical_map(self, _name, query):
        # The `attributes` column is an ALIAS that rebuilds the whole map from `attributes_map_str` per row. A bare key
        # must route to the suffixed key on the physical map instead, or a SELECT over 30 days reads every attribute.
        runner = HogQLQueryRunner(query=HogQLQuery(query=query, modifiers=OPTIMIZED), team=self.team)
        sql = runner.calculate().clickhouse or ""
        assert "attributes_map_str" in sql
        assert "has(attributes," not in sql
        assert "attributes[" not in sql

    @parameterized.expand([("alias", None), ("property_group", OPTIMIZED)])
    def test_bare_attribute_key_reads_the_same_value_as_the_alias(self, _name, modifiers):
        sync_execute(
            "INSERT INTO logs FORMAT JSONEachRow\n"
            + json.dumps(
                {
                    "team_id": self.team.id,
                    "timestamp": "2026-06-23 12:00:00.000000",
                    "body": "retry_summary",
                    "severity_text": "info",
                    "service_name": "api",
                    "attributes_map_str": {"retry_reason__str": "upstream_timeout", "retried__str": "true"},
                }
            )
        )
        query = (
            "SELECT attributes.retry_reason, attributes['retry_reason'], attributes.missing, "
            "countIf(attributes.retried = 'true') FROM logs GROUP BY 1, 2, 3"
        )
        runner = HogQLQueryRunner(query=HogQLQuery(query=query, modifiers=modifiers), team=self.team)
        assert runner.calculate().results == [("upstream_timeout", "upstream_timeout", None, 1)]
