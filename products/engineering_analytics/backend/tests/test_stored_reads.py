from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.errors import QueryError

from posthog.exceptions import ClickHouseAtCapacity

from products.engineering_analytics.backend.logic.queries._curated import STORED_QUERY_TYPE_SUFFIX, CuratedGitHubSource
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    GITHUB_SOURCE_PREFIX,
    create_github_source,
    create_warehouse_table_row,
    link_schema,
)
from products.engineering_analytics.backend.tests._logic_helpers import _CI_PRECOMPUTE, _CURATED

_RAW_READ = "engineering_analytics.test"
_STORED_READ = f"{_RAW_READ}{STORED_QUERY_TYPE_SUFFIX}"


class TestStoredReads(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        source = create_github_source(self.team, repository="PostHog/posthog")
        for schema in (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA):
            table = create_warehouse_table_row(self.team, name=f"{GITHUB_SOURCE_PREFIX}github_{schema}", source=source)
            link_schema(self.team, source, name=schema, table=table)

    @parameterized.expand(
        [
            ("every_day_is_stored", True, True, None, [_STORED_READ, _STORED_READ], True),
            ("flag_off", False, True, None, [_RAW_READ, _RAW_READ], True),
            ("a_day_is_not_stored", True, False, None, [_RAW_READ, _RAW_READ], True),
            (
                "stored_rows_reject_the_query",
                True,
                True,
                QueryError("no such column"),
                [_STORED_READ, _RAW_READ, _RAW_READ],
                True,
            ),
            ("stored_read_lacks_capacity", True, True, ClickHouseAtCapacity(), [_STORED_READ], False),
        ]
    )
    def test_two_floored_reads_take_the_stored_rows_only_while_they_answer(
        self,
        _name: str,
        flag: bool,
        days_stored: bool,
        stored_error: Exception | None,
        expected_reads: list[str],
        answered: bool,
    ) -> None:
        curated = CuratedGitHubSource.for_team(self.team)
        sql = f"SELECT count() FROM {curated.run_source(started_floor=True)} AS r"
        floor = timezone.now().strftime("%Y-%m-%d")

        def execute(**kwargs: Any) -> SimpleNamespace:
            if stored_error is not None and kwargs["query_type"] == _STORED_READ:
                raise stored_error
            return SimpleNamespace(results=[(1,)])

        def read() -> list[Any]:
            placeholders: dict[str, ast.Expr] = {"run_started_floor": ast.Constant(value=floor)}
            return curated.run(sql, query_type=_RAW_READ, placeholders=placeholders).results

        with (
            patch(f"{_CURATED}.team_flag", return_value=flag),
            patch(
                f"{_CI_PRECOMPUTE}.ensure_stored",
                return_value=SimpleNamespace(ready=days_stored, job_ids=[uuid4()]),
            ),
            patch(f"{_CURATED}.execute_hogql_query", side_effect=execute) as mock_execute,
        ):
            if answered:
                assert [read(), read()] == [[(1,)], [(1,)]]
            else:
                assert stored_error is not None
                with self.assertRaises(type(stored_error)):
                    read()

        assert [call.kwargs["query_type"] for call in mock_execute.call_args_list] == expected_reads
