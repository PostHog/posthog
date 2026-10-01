from collections.abc import Callable

from django.test import SimpleTestCase

from parameterized import parameterized

from products.engineering_analytics.backend.logic.views import depot_ci, workflow_jobs, workflow_runs

_RUNS = "raw_workflow_runs"
_JOBS = "raw_workflow_jobs"
_PULL_REQUESTS = "raw_pull_requests"
_DEPOT = "raw_depot_job_attempts"

_DEPOT_ATTEMPTS = depot_ci.DepotJobAttempts(table=_DEPOT, repository="PostHog/posthog")


def _runs_source() -> str:
    table = depot_ci.with_depot_runs(_RUNS, _DEPOT_ATTEMPTS, _PULL_REQUESTS, _JOBS)
    return workflow_runs.build_query(table, pull_requests_table=_PULL_REQUESTS, started_floor=True)


def _jobs_source() -> str:
    return workflow_jobs.build_query(
        depot_ci.with_depot_jobs(_JOBS, _DEPOT_ATTEMPTS, _RUNS),
        created_floor=True,
        duplicates_table=depot_ci.with_depot_jobs(_JOBS, _DEPOT_ATTEMPTS, runs_table=None),
    )


class TestSourceScanBudget(SimpleTestCase):
    @parameterized.expand(
        [
            ("runs_source", _runs_source, {_RUNS: 2, _JOBS: 3, _PULL_REQUESTS: 2, _DEPOT: 7}),
            ("jobs_source", _jobs_source, {_RUNS: 1, _JOBS: 5, _PULL_REQUESTS: 0, _DEPOT: 14}),
        ]
    )
    def test_source_reads_each_warehouse_table_within_its_budget(
        self, _name: str, render: Callable[[], str], budget: dict[str, int]
    ) -> None:
        sql = render()
        reads = {table: sql.count(table) for table in budget}
        assert reads == budget, (
            "Every read embeds these sources, and a page load runs about twenty reads, so one more "
            "table read here multiplies across all of them. Measure read_rows for the new SQL in "
            "production before you change a budget."
        )
