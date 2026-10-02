from datetime import timedelta
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

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet, DataWarehouseSavedQuery
from products.engineering_analytics.backend.logic.queries._curated import STORED_QUERY_TYPE_SUFFIX, CuratedGitHubSource
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.engineering_analytics.backend.logic.stored_views import StoredTables, stored_tables_for
from products.engineering_analytics.backend.logic.views import ci_jobs, ci_runs
from products.engineering_analytics.backend.logic.views.stored_view import identity_columns
from products.engineering_analytics.backend.tests._github_fixtures import (
    GITHUB_SOURCE_PREFIX,
    create_github_source,
    create_warehouse_table_row,
    link_schema,
)
from products.engineering_analytics.backend.tests._logic_helpers import _CURATED
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

_STORED_VIEWS = "products.engineering_analytics.backend.logic.stored_views"
_BOTH_VIEWS = (ci_runs.VIEW_NAME, ci_jobs.VIEW_NAME)
_REPOSITORY = "PostHog/posthog"
_RAW_READ = "engineering_analytics.test"
_STORED_READ = f"{_RAW_READ}{STORED_QUERY_TYPE_SUFFIX}"


class TestStoredReads(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = create_github_source(self.team, repository=_REPOSITORY)
        self.raw_tables = []
        for schema in (PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA):
            table = create_warehouse_table_row(
                self.team, name=f"{GITHUB_SOURCE_PREFIX}github_{schema}", source=self.source
            )
            link_schema(self.team, self.source, name=schema, table=table)
            self.raw_tables.append(table.name)

    @parameterized.expand(
        [
            ("served", True, _BOTH_VIEWS, True, 5, 24 * 60, True),
            ("flag_off", False, _BOTH_VIEWS, True, 5, 24 * 60, False),
            ("jobs_view_missing", True, (ci_runs.VIEW_NAME,), True, 5, 24 * 60, False),
            ("source_not_in_the_views", True, _BOTH_VIEWS, False, 5, 24 * 60, False),
            ("never_built", True, _BOTH_VIEWS, True, None, 24 * 60, False),
            ("built_too_long_ago", True, _BOTH_VIEWS, True, 120, 24 * 60, False),
            ("raw_table_landed_after_the_build", True, _BOTH_VIEWS, True, 5, 0, False),
        ]
    )
    def test_tables_are_served_only_when_recent_and_built_for_the_source(
        self,
        _name: str,
        flag: bool,
        view_names: tuple[str, ...],
        source_in_views: bool,
        built_minutes_ago: int | None,
        raw_tables_landed_minutes_ago: int,
        served: bool,
    ) -> None:
        now = timezone.now()
        source_id = str(self.source.id)
        viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
        )
        identity = identity_columns(source_id if source_in_views else str(uuid4()), _REPOSITORY)
        for name in view_names:
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=name,
                query={"kind": "HogQLQuery", "query": f"SELECT 1, {identity}"},
                managed_viewset=viewset,
                is_materialized=True,
            )
        DataWarehouseTable.objects.filter(team=self.team).update(
            created_at=now - timedelta(minutes=raw_tables_landed_minutes_ago)
        )
        built_at = None if built_minutes_ago is None else now - timedelta(minutes=built_minutes_ago)

        with (
            patch("posthoganalytics.feature_enabled", return_value=flag),
            patch(f"{_STORED_VIEWS}.data_modeling.saved_query_materialized_at", return_value=built_at),
        ):
            tables = stored_tables_for(
                self.team, None, source_id=source_id, repository=_REPOSITORY, raw_tables=self.raw_tables
            )

        assert (tables is not None) is served

    @parameterized.expand(
        [
            ("floor_inside_the_stored_window", 10, True, None, [_STORED_READ], True),
            ("floor_below_the_stored_window", 200, True, None, [_RAW_READ], True),
            ("views_missing_from_the_reader_catalog", 10, False, None, [_RAW_READ], True),
            ("stored_tables_reject_the_query", 10, True, QueryError("no such column"), [_STORED_READ, _RAW_READ], True),
            ("stored_read_lacks_capacity", 10, True, ClickHouseAtCapacity(), [_STORED_READ], False),
        ]
    )
    def test_floored_read_takes_the_stored_tables_only_when_they_answer_it(
        self,
        _name: str,
        floor_days_ago: int,
        views_in_catalog: bool,
        stored_error: Exception | None,
        expected_reads: list[str],
        answered: bool,
    ) -> None:
        now = timezone.now()
        if views_in_catalog:
            for view_name in _BOTH_VIEWS:
                DataWarehouseSavedQuery.objects.create(
                    team=self.team, name=view_name, query={"kind": "HogQLQuery", "query": "SELECT 1"}
                )
        curated = CuratedGitHubSource.for_team(self.team)
        sql = f"SELECT count() FROM {curated.run_source(started_floor=True)} AS r"
        floor = (now - timedelta(days=floor_days_ago)).strftime("%Y-%m-%d")

        def execute(**kwargs: Any) -> SimpleNamespace:
            if stored_error is not None and kwargs["query_type"] == _STORED_READ:
                raise stored_error
            return SimpleNamespace(results=[(1,)])

        def read() -> list[Any]:
            placeholders: dict[str, ast.Expr] = {"run_started_floor": ast.Constant(value=floor)}
            return curated.run(sql, query_type=_RAW_READ, placeholders=placeholders).results

        with (
            patch(f"{_CURATED}.stored_tables_for", return_value=StoredTables(built_at=dict.fromkeys(_BOTH_VIEWS, now))),
            patch(f"{_CURATED}.execute_hogql_query", side_effect=execute) as mock_execute,
        ):
            if answered:
                assert read() == [(1,)]
            else:
                with self.assertRaises(type(stored_error)):
                    read()

        assert [call.kwargs["query_type"] for call in mock_execute.call_args_list] == expected_reads
