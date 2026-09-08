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

    @parameterized.expand(
        [
            ("equals", "SELECT count() FROM logs WHERE body = 'Error'", True),
            ("equals_reversed", "SELECT count() FROM logs WHERE 'Error' = body", True),
            ("equals_message_alias", "SELECT count() FROM logs WHERE message = 'Error'", True),
            ("equals_tostring", "SELECT count() FROM logs WHERE toString(body) = 'Error'", True),
            ("like", "SELECT count() FROM logs WHERE body LIKE '%Error%'", True),
            ("in_list", "SELECT count() FROM logs WHERE body IN ('Error', 'Warning')", True),
            ("not_equals", "SELECT count() FROM logs WHERE body != 'Error'", False),
            ("equals_column", "SELECT count() FROM logs WHERE body = service_name", False),
            ("other_column", "SELECT count() FROM logs WHERE service_name = 'api'", False),
        ]
    )
    def test_body_constant_comparison_keeps_lower_index_hint(self, _name, query, expects_hint):
        # idx_body_ngram3 is built on lower(body), so a comparison against the bare column reads every granule. The
        # printed SQL must keep the original case-sensitive comparison and add an indexHint over lower(body).
        runner = HogQLQueryRunner(query=HogQLQuery(query=query), team=self.team)
        response = runner.calculate()
        sql = response.clickhouse or ""
        assert ("indexHint(" in sql) == expects_hint
        assert ("lower(logs_distributed.body)" in sql) == expects_hint
        if expects_hint:
            bare_body_reads = sql.replace("lower(logs_distributed.body)", "").count("logs_distributed.body")
            assert bare_body_reads == 1
