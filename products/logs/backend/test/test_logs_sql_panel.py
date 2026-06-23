from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import HogQLQuery

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner


class TestLogsSqlPanel(ClickhouseTestMixin, APIBaseTest):
    def test_attribute_filter_uses_map_not_json(self):
        # Arbitrary HogQL from the SQL panel reads logs attributes via the `attributes_map_str` Map column.
        # This relies on the LOGS workload forcing propertyGroupsMode=OPTIMIZED; without it the read falls
        # back to JSONExtract, which is illegal on a Map and errors at execution time.
        runner = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT count() FROM logs WHERE attributes.`log.iostream__str` = 'stderr'"),
            team=self.team,
        )
        response = runner.calculate()
        sql = response.clickhouse or ""
        assert "JSONExtract" not in sql
        assert "attributes_map_str" in sql

    def test_unsuffixed_attribute_key_uses_map_not_json(self):
        # A user types the attribute key as it appears in the UI — unsuffixed (`attributes.my_key`), not with the
        # internal `__str` type suffix. That key resolves to the unsuffixed `attributes` alias Map column. Without the
        # fallback property group it would resolve to JSONExtract, which is illegal on a Map and errors at execution.
        runner = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT count() FROM logs WHERE attributes.tennis_session_id = 'abc'"),
            team=self.team,
        )
        response = runner.calculate()
        sql = response.clickhouse or ""
        assert "JSONExtract" not in sql
        # Map subscript on the unsuffixed `attributes` alias column, not the typed `attributes_map_str` map.
        assert "attributes[" in sql
        assert "attributes_map_str" not in sql

    def test_unsuffixed_attribute_key_bracket_syntax_uses_map_not_json(self):
        # The bracket form `attributes['my_key']` must behave identically to the dot form — both are Map access, not
        # JSONExtract. (Previously both compiled to the same illegal JSONExtract, so "Fix with AI" flipping between
        # them changed nothing.)
        runner = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT count() FROM logs WHERE attributes['tennis_session_id'] = 'abc'"),
            team=self.team,
        )
        response = runner.calculate()
        sql = response.clickhouse or ""
        assert "JSONExtract" not in sql
        assert "attributes[" in sql
        assert "attributes_map_str" not in sql
