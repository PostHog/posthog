from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner


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
