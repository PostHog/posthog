"""Check the stored CI rows against the raw tables: each query that a read serves from the stored rows
runs again on the raw tables, and the two results are compared row for row.

A stored read and its raw read differ by design in two bounded flags (SPEC, "Stored CI rows"), and
by the rows that changed between the last refresh and now. So a difference is a lead to check, not
proof of a bug: read it next to the age of the stored rows.
"""

import threading
from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from posthog.hogql import ast
from posthog.hogql.query import HogQLQueryResponse

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.engineering_analytics.backend.logic.pull_requests import build_pr_cost, build_pull_request_list
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.workflows import (
    build_job_aggregates,
    build_master_failures,
    build_repo_overview,
    build_workflow_health,
    build_workflow_runner_costs,
)

# Sums of floats come out in a different order from the two tables.
_SIGNIFICANT_DIGITS = 9


@frozen
class QueryParity:
    query_type: str
    stored_rows: int
    raw_rows: int
    only_stored: int
    only_raw: int
    sample_only_stored: str | None
    sample_only_raw: str | None
    raw_error: str | None

    @property
    def equal(self) -> bool:
        return self.raw_error is None and not self.only_stored and not self.only_raw


def _normalized(value: Any) -> Any:
    # The two tables can type one column differently (Bool against UInt8, Float64 against Int64).
    if isinstance(value, bool | int):
        return int(value)
    if isinstance(value, float | Decimal):
        number = float(f"{float(value):.{_SIGNIFICANT_DIGITS}g}")
        return int(number) if number.is_integer() else number
    if isinstance(value, list | tuple):
        return tuple(_normalized(item) for item in value)
    return value


def _differing_rows(rows: Sequence[Sequence[Any]], other: Sequence[Sequence[Any]]) -> Counter[str]:
    # Row order is compared only where the query fixes it, and a LIMIT can cut tied rows either way,
    # so the rows are compared as multisets.
    return Counter(repr(_normalized(row)) for row in rows) - Counter(repr(_normalized(row)) for row in other)


@frozen
class StoredReadParity:
    """The comparisons of the reads that the stored rows answered, and the query types that could
    have read the stored rows but read the raw tables, so went unchecked."""

    queries: tuple[QueryParity, ...]
    raw_reads: tuple[str, ...]


class ParityCheckedGitHubSource(CuratedGitHubSource):
    """A read handle that runs each read the stored rows answer on the raw tables too. It doubles the
    cost of those reads, and it reads no cache, so only a check uses it."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._parity_lock = threading.Lock()
        # Concurrent reads of one request run in threads, and each run asks whether its own read was answered.
        self._answered = threading.local()
        self.queries: list[QueryParity] = []
        self.raw_reads: list[str] = []

    def run(
        self,
        sql: str,
        *,
        query_type: str,
        placeholders: dict[str, ast.Expr] | None = None,
        workload: Workload = Workload.DEFAULT,
    ) -> HogQLQueryResponse:
        self._answered.value = False
        response = super().run(sql, query_type=query_type, placeholders=placeholders, workload=workload)
        if not self._answered.value and self._with_raw_ci_sources(sql) != sql:
            with self._parity_lock:
                self.raw_reads.append(query_type)
        return response

    def read_through[V](
        self, *, sql: str, keys: Sequence[int], load: Callable[[list[int]], dict[int, V]], ttl_seconds: int
    ) -> dict[int, V]:
        return load(list(keys))

    def _stored_read_answered(
        self,
        sql: str,
        response: HogQLQueryResponse,
        *,
        query_type: str,
        placeholders: dict[str, ast.Expr] | None,
    ) -> None:
        self._answered.value = True
        stored = response.results or []
        raw: list[Any] = []
        raw_error = None
        try:
            raw = (
                self._execute(
                    self._with_raw_ci_sources(sql),
                    query_type=query_type,
                    placeholders=placeholders,
                    workload=Workload.DEFAULT,
                ).results
                or []
            )
        except Exception as error:
            raw_error = repr(error)
        only_stored = _differing_rows(stored, raw)
        only_raw = _differing_rows(raw, stored)
        with self._parity_lock:
            self.queries.append(
                QueryParity(
                    query_type=query_type,
                    stored_rows=len(stored),
                    raw_rows=len(raw),
                    only_stored=only_stored.total(),
                    only_raw=only_raw.total(),
                    sample_only_stored=next(iter(only_stored), None),
                    sample_only_raw=next(iter(only_raw), None),
                    raw_error=raw_error,
                )
            )


def compare_stored_reads(*, team: Team, source_id: str | None, repo: str | None, days: int) -> StoredReadParity:
    """Run the main CI reads of one repository over the last ``days``, with every read that the stored
    rows answer checked against the raw tables."""
    curated = ParityCheckedGitHubSource.for_team(team, source_id=source_id, repo=repo)
    date_from = f"-{days}d"
    build_repo_overview(curated=curated, date_from=date_from)
    workflows = build_workflow_health(curated=curated, date_from=date_from)
    build_master_failures(curated=curated, date_from=date_from)
    for workflow in workflows[:1]:
        build_job_aggregates(curated=curated, workflow_name=workflow.workflow_name, date_from=date_from)
        build_workflow_runner_costs(
            curated=curated, repo=curated.repository, workflow_name=workflow.workflow_name, date_from=date_from
        )
    pull_requests = build_pull_request_list(curated=curated, date_from=date_from)
    for pull_request in pull_requests.items[:1]:
        build_pr_cost(curated=curated, pr_number=pull_request.number, repo=curated.repository)
    return StoredReadParity(queries=tuple(curated.queries), raw_reads=tuple(curated.raw_reads))
