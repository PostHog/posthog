from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache.backends.locmem import LocMemCache
from django.db import OperationalError
from django.utils import timezone

from clickhouse_driver.errors import SocketTimeoutError, UnknownPacketFromServerError
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
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

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
            ("every_day_is_stored", True, None, [_STORED_READ, _STORED_READ], True),
            ("a_day_is_not_stored", False, None, [_RAW_READ, _RAW_READ], True),
            ("the_stored_days_lookup_fails", OperationalError("down"), None, [_RAW_READ, _RAW_READ], True),
            (
                "stored_rows_reject_the_query",
                True,
                QueryError("no such column"),
                [_STORED_READ, _RAW_READ, _RAW_READ],
                True,
            ),
            ("stored_read_lacks_capacity", True, ClickHouseAtCapacity(), [_STORED_READ], False),
            ("stored_read_loses_its_connection", True, SocketTimeoutError(), [_STORED_READ], False),
            ("stored_read_misreads_the_protocol", True, UnknownPacketFromServerError(), [_STORED_READ], False),
        ]
    )
    def test_two_floored_reads_take_the_stored_rows_only_while_they_answer(
        self,
        _name: str,
        days_stored: bool | Exception,
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

        lookup: dict[str, Any] = (
            {"side_effect": days_stored}
            if isinstance(days_stored, Exception)
            else {"return_value": SimpleNamespace(ready=days_stored, job_ids=[uuid4()])}
        )

        with (
            patch(f"{_CI_PRECOMPUTE}.cache", LocMemCache(self.id(), {})),
            patch(f"{_CI_PRECOMPUTE}.history_start", return_value=timezone.now() - timedelta(days=400)),
            patch(f"{_CURATED}._start_refresh") as mock_refresh,
            patch(f"{_CI_PRECOMPUTE}.ensure_stored", **lookup),
            patch(f"{_CURATED}.execute_hogql_query", side_effect=execute) as mock_execute,
        ):
            if answered:
                assert [read(), read()] == [[(1,)], [(1,)]]
            else:
                assert stored_error is not None
                with self.assertRaises(type(stored_error)):
                    read()

        assert [call.kwargs["query_type"] for call in mock_execute.call_args_list] == expected_reads
        # The first read that can take the stored rows starts a refresh, because no load refreshed them
        # while the team was not in use.
        assert mock_refresh.call_count == 1

    @parameterized.expand(
        [
            ("first_day_known", timezone.now() - timedelta(days=400), [_STORED_READ]),
            ("first_day_not_found_yet", None, [_RAW_READ]),
        ]
    )
    def test_a_read_keyed_by_pull_request_takes_the_stored_rows_of_the_whole_history(
        self, _name: str, first_day: datetime | None, expected_reads: list[str]
    ) -> None:
        curated = CuratedGitHubSource.for_team(self.team)
        sql = f"SELECT count() FROM {curated.run_source(stored_history=True)} AS r"

        with (
            patch(f"{_CI_PRECOMPUTE}.cache", LocMemCache(self.id(), {})),
            patch(f"{_CI_PRECOMPUTE}.history_start", return_value=first_day),
            patch(
                f"{_CI_PRECOMPUTE}.ensure_stored", return_value=SimpleNamespace(ready=True, job_ids=[uuid4()])
            ) as mock_ensure,
            patch(f"{_CURATED}.execute_hogql_query", return_value=SimpleNamespace(results=[(1,)])) as mock_execute,
        ):
            curated.run(sql, query_type=_RAW_READ)

        assert [call.kwargs["query_type"] for call in mock_execute.call_args_list] == expected_reads
        # With no floor, the read needs every stored day from the first day of the history.
        assert {call.kwargs["since"] for call in mock_ensure.call_args_list} == ({first_day} if first_day else set())

    @parameterized.expand(
        [
            ("stored_rows_older_than_the_sync", True, timedelta(minutes=30), timedelta(minutes=30)),
            ("stored_rows_newer_than_the_sync", True, timedelta(minutes=1), timedelta(minutes=5)),
            ("flag_off", False, timedelta(minutes=30), timedelta(minutes=5)),
            ("the_stored_days_lookup_fails", True, OperationalError("down"), timedelta(minutes=5)),
        ]
    )
    def test_ci_data_freshness_is_as_old_as_the_stored_rows_reads_take(
        self, _name: str, flag: bool, stored_age: timedelta | Exception, expected_age: timedelta
    ) -> None:
        now = timezone.now()
        ExternalDataSchema.objects.filter(team=self.team).update(last_synced_at=now - timedelta(minutes=5))
        lookup: dict[str, Any] = (
            {"side_effect": stored_age}
            if isinstance(stored_age, Exception)
            else {"return_value": SimpleNamespace(ready=True, job_ids=[uuid4()], computed_at=now - stored_age)}
        )

        with (
            patch(f"{_CI_PRECOMPUTE}.cache", LocMemCache(self.id(), {})),
            patch(f"{_CURATED}.refresh_ci_precompute"),
            patch(f"{_CURATED}.team_flag", return_value=flag),
            patch(f"{_CI_PRECOMPUTE}.history_start", return_value=now - timedelta(days=400)),
            patch(f"{_CI_PRECOMPUTE}.ensure_stored", **lookup),
        ):
            freshness = CuratedGitHubSource.for_team(self.team).ci_data_freshness()

        assert freshness.as_of == now - expected_age
