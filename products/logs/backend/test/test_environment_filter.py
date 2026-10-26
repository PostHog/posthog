import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from products.logs.backend.environment_filter import (
    UNLABELED_ENVIRONMENT,
    environment_filter_expr,
    rollup_environment_filter_expr,
)
from products.logs.backend.test.volume_rollup_fixtures import insert_logs_and_rollups, log_row

_AT = dt.datetime(2026, 6, 23, 12, 1, tzinfo=dt.UTC)


class TestEnvironmentFilter(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        resources = [
            ("name-key", {"deployment.environment.name": "production", "env": "staging"}),
            ("legacy-key", {"deployment.environment": "production"}),
            ("short-key", {"env": "Production"}),
            ("empty-name-falls-back", {"deployment.environment.name": "", "env": "staging"}),
            ("unlabeled", {"k8s.namespace.name": "default"}),
        ]
        insert_logs_and_rollups(
            [log_row(cls.team.id, _AT, service=service, resource_attributes=attrs) for service, attrs in resources]
        )

    def _raw_services(self, environment: str) -> set[str]:
        query = parse_select(
            "SELECT DISTINCT service_name FROM logs WHERE {env}",
            placeholders={"env": environment_filter_expr(environment)},
        )
        return {row[0] for row in execute_hogql_query(query=query, team=self.team).results}

    def _rollup_services(self, environment: str) -> set[str]:
        query = parse_select(
            "SELECT DISTINCT service_name FROM posthog.logs_volume_buckets WHERE {env}",
            placeholders={"env": rollup_environment_filter_expr(environment)},
        )
        assert isinstance(query, ast.SelectQuery)
        return {row[0] for row in execute_hogql_query(query=query, team=self.team).results}

    @parameterized.expand(
        [
            ("production", "production", {"name-key", "legacy-key", "short-key"}),
            ("case_insensitive", "PRODUCTION", {"name-key", "legacy-key", "short-key"}),
            ("staging_only_where_no_higher_key", "staging", {"empty-name-falls-back"}),
            ("unlabeled", UNLABELED_ENVIRONMENT, {"unlabeled"}),
            ("unknown", "qa", set()),
        ]
    )
    def test_raw_filter_follows_the_rollup_fallback_chain(self, _name: str, environment: str, expected: set[str]):
        assert self._raw_services(environment) == expected
        assert self._rollup_services(environment) == expected
