"""Check the stored CI rows against the raw tables: each query that a read serves from the stored rows
runs again on the raw tables, and the two results are compared row for row.

A stored read and its raw read differ by design in two bounded flags (SPEC, "Stored CI rows"), and
by the rows that changed between the last refresh and now. So a difference is a lead to check, not
proof of a bug: read it next to the age of the stored rows.
"""

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
    only_stored: tuple[str, ...]
    only_raw: tuple[str, ...]
    raw_error: str | None

    @property
    def equal(self) -> bool:
        return self.raw_error is None and not (self.only_stored or self.only_raw)


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


def _row_counts(rows: Sequence[Sequence[Any]]) -> Counter[str]:
    # Row order is compared only where the query fixes it, and a LIMIT can cut tied rows either way,
    # so the rows are compared as multisets.
    return Counter(repr(_normalized(row)) for row in rows)


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
        self.queries: list[QueryParity] = []
        self.raw_reads: list[str] = []

    def read_through[V](
        self, *, sql: str, keys: Sequence[int], load: Callable[[list[int]], dict[int, V]], ttl_seconds: int
    ) -> dict[int, V]:
        return load(list(keys))

    def _ci_read_done(
        self,
        sql: str,
        response: HogQLQueryResponse,
        *,
        query_type: str,
        placeholders: dict[str, ast.Expr] | None,
        stored: bool,
    ) -> None:
        if not stored:
            if self._with_raw_ci_sources(sql) != sql:
                self.raw_reads.append(query_type)
            return
        stored_rows = response.results or []
        raw_rows: list[Any] = []
        raw_error = None
        try:
            raw_rows = (
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
        stored_counts, raw_counts = _row_counts(stored_rows), _row_counts(raw_rows)
        self.queries.append(
            QueryParity(
                query_type=query_type,
                stored_rows=len(stored_rows),
                raw_rows=len(raw_rows),
                only_stored=tuple((stored_counts - raw_counts).elements()),
                only_raw=tuple((raw_counts - stored_counts).elements()),
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
