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
