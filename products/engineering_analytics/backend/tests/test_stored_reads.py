from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql import ast

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet, DataWarehouseSavedQuery
from products.engineering_analytics.backend.logic.queries._curated import STORED_QUERY_TYPE_SUFFIX, CuratedGitHubSource
from products.engineering_analytics.backend.logic.sources import (
    PULL_REQUESTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.engineering_analytics.backend.logic.stored_views import StoredTables, servable_tables
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
            # A table with no row for the source reads the same as a repository with no CI.
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
            tables = servable_tables(
                self.team, None, source_id=source_id, repository=_REPOSITORY, raw_tables=self.raw_tables
            )

        assert (tables is not None) is served

    @parameterized.expand(
        [
            ("floor_inside_the_stored_window", 10, False, False, [_STORED_READ]),
            # The stored tables keep a rolling window, so a longer range would lose its oldest rows.
            ("floor_below_the_stored_window", 200, False, False, [_RAW_READ]),
            ("query_also_reads_a_raw_ci_table", 10, True, False, [_RAW_READ]),
            ("stored_read_fails", 10, False, True, [_STORED_READ, _RAW_READ]),
        ]
    )
    def test_floored_read_takes_the_stored_tables_only_when_they_answer_it(
        self,
        _name: str,
        floor_days_ago: int,
        reads_unfloored_source: bool,
        stored_read_fails: bool,
        expected_reads: list[str],
    ) -> None:
        now = timezone.now()
        curated = CuratedGitHubSource.for_team(self.team)
        sql = f"SELECT count() FROM {curated.run_source(started_floor=True)} AS r"
        if reads_unfloored_source:
            sql += f" WHERE r.id IN (SELECT id FROM {curated.run_source()} AS unfloored)"
        floor = (now - timedelta(days=floor_days_ago)).strftime("%Y-%m-%d")

        def execute(**kwargs: Any) -> SimpleNamespace:
            if stored_read_fails and kwargs["query_type"] == _STORED_READ:
                raise RuntimeError("the stored table has no such column")
            return SimpleNamespace(results=[(1,)])

        with (
            patch(f"{_CURATED}.servable_tables", return_value=StoredTables(runs_built_at=now, jobs_built_at=now)),
            patch(f"{_CURATED}.execute_hogql_query", side_effect=execute) as mock_execute,
        ):
            response = curated.run(
                sql, query_type=_RAW_READ, placeholders={"run_started_floor": ast.Constant(value=floor)}
            )

        assert [call.kwargs["query_type"] for call in mock_execute.call_args_list] == expected_reads
        assert response.results == [(1,)]
