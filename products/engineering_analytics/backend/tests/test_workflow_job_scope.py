import pytest

from parameterized import parameterized

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import CIEngine
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.workflow_jobs import query_workflow_job
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import (
    _depot_attempt_row,
    _pr_row,
    _run_row,
    pr_association,
)
from products.engineering_analytics.backend.tests._logic_helpers import (
    _ago,
    _ago_with_duration,
    _job_row,
    _WarehouseMixin,
)


class TestWorkflowJobScope(_WarehouseMixin):
    @parameterized.expand(
        [
            ("successful_shell", False, False, True, 1),
            ("recovered_after_old_failure", True, False, True, 1),
            ("queue_handoff", False, True, True, 1),
            ("queue_snapshot_pending", False, True, False, 1),
            ("handoff_job_older_than_its_depot_workflow", False, False, True, 5),
        ]
    )
    def test_single_run_job_scope_preserves_handoff_failure_evidence(
        self, _: str, had_old_failure: bool, is_queue: bool, gate_snapshot_synced: bool, handoff_job_age_days: int
    ) -> None:
        queue_branch = "trunk-merge/pr-62/invented-gate"
        source_pr = 900999 if is_queue else 62
        started, completed = _ago_with_duration(1, 120)
        first_handoff_started, first_handoff_completed = _ago_with_duration(10, 120)
        first_handoff = _depot_attempt_row(
            repo="PostHog/posthog",
            run_id="5555555555",
            workflow_id="6666666666",
            ref="refs/pull/77/merge",
            head_sha="sha77",
            workflow_status="finished",
            workflow_created_at=first_handoff_started,
            workflow_started_at=first_handoff_started,
            workflow_finished_at=first_handoff_completed,
            attempt_status="finished",
            attempt_started_at=first_handoff_started,
            attempt_finished_at=first_handoff_completed,
            job_key="ci.yml:wait-for-handoff",
            job_id="7777777777",
            attempt_id="8888888888",
        )
        self._create_depot_table(
            [
                {
                    **_depot_attempt_row(
                        repo="PostHog/posthog",
                        ref=f"refs/pull/{source_pr}/merge",
                        head_sha="sha62",
                        workflow_status="finished",
                        workflow_created_at=started,
                        workflow_started_at=started,
                        workflow_finished_at=completed,
                        attempt_status="finished",
                        attempt_started_at=started,
                        attempt_finished_at=completed,
                        job_key=key,
                        job_id=job_id,
                        attempt_id=attempt_id,
                    ),
                    **({"head_sha": None, "sha": "sha62"} if key.endswith(":tests") else {}),
                }
                for key, job_id, attempt_id in (
                    ("ci.yml:wait-for-handoff", "1111111111", "2222222222"),
                    ("ci.yml:tests", "3333333333", "4444444444"),
                )
            ]
            + [first_handoff],
        )
        pr_rows = [_pr_row(62, "alice", "open", 0, _ago(21), head_sha="sha62")]
        if is_queue and gate_snapshot_synced:
            pr_rows.append(
                _pr_row(source_pr, "trunk-io[bot]", "closed", 0, _ago(40), closed_at=_ago(40), head_ref=queue_branch)
            )
        self._create_table("github_pull_requests", PULL_REQUESTS_COLUMNS, pr_rows)
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                {
                    **_run_row(
                        9200,
                        "CI",
                        "sha62",
                        "completed",
                        "success",
                        started,
                        completed,
                        run_attempt=2,
                        pr_number=source_pr,
                        head_branch=queue_branch if is_queue else "main",
                        actor="trunk-io[bot]" if is_queue else "alice",
                    ),
                    "created_at": _ago(20),
                }
            ],
        )
        handoff_started, handoff_completed = _ago_with_duration(handoff_job_age_days, 120)
        handoff_times = {"started": handoff_started, "completed": handoff_completed}
        jobs = [
            _job_row(92001, 9200, "Hand off backend tests to Depot CI", "success", run_attempt=2, **handoff_times),
            _job_row(92002, 9200, "Django Tests Pass", "success", run_attempt=2, **handoff_times),
            _job_row(93001, 9300, "unrelated failure", "failure"),
        ]
        if had_old_failure:
            old_start, old_end = _ago_with_duration(20, 120)
            jobs.append(_job_row(92000, 9200, "Django Tests Pass", "failure", started=old_start, completed=old_end))
        self._create_table("github_workflow_jobs", WORKFLOW_JOBS_COLUMNS, jobs)
        observed = api.list_workflow_jobs(team=self.team, run_id=9200, ci_engine=CIEngine.GITHUB_ACTIONS)
        assert {job.id for job in observed} == ({92001, 92002} if had_old_failure else set())
        curated = CuratedGitHubSource.for_team(self.team)
        detail = query_workflow_job(curated=curated, run_id=9200, job_id=92002, ci_engine=CIEngine.GITHUB_ACTIONS)
        assert (detail is not None) == had_old_failure
        if had_old_failure:
            earlier = api.list_workflow_jobs(
                team=self.team, run_id=9200, run_attempt=1, ci_engine=CIEngine.GITHUB_ACTIONS
            )
            assert [job.id for job in earlier] == [92000]
        listed = api.list_pull_requests(team=self.team).items[0]
        lifetime_cost = api.get_pr_cost(team=self.team, pr_number=62, repo="PostHog/posthog")
        assert listed.estimated_cost_usd == lifetime_cost.estimated_cost_usd
        assert (listed.billable_minutes or 0) == lifetime_cost.billable_minutes
        assert listed.ci.runs > 0
        assert listed.pushes == (0 if is_queue else 1)
        assert [sample.head_sha for sample in listed.push_history] == ([] if is_queue else ["sha62"])

    def test_pr_scope_keeps_lifetime_association_costs_and_shared_head_ci(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _pr_row(700070, "alice", "open", 0, _ago(1), head_sha="shared-head"),
                _pr_row(700071, "bob", "open", 0, _ago(0), head_sha="another-head"),
            ],
        )
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [
                _run_row(9400, "CI", "old-head", "completed", "success", _ago(40), _ago(40), pr_number=700070),
                _run_row(9401, "CI", "shared-head", "completed", "success", _ago(1), _ago(1), pr_number=700071),
                _run_row(
                    9402,
                    "CI",
                    "queue-head",
                    "completed",
                    "success",
                    _ago(1),
                    _ago(1),
                    pr_number=900001,
                    head_branch="trunk-merge/pr-700070/invented-gate",
                    actor="trunk-io[bot]",
                ),
                {
                    **_run_row(9403, "CI", "foreign-head", "completed", "failure", _ago(1), _ago(1)),
                    "pull_requests": pr_association(700070, base_repo="example/another-repository"),
                },
            ],
        )
        self._create_table(
            "github_workflow_jobs",
            WORKFLOW_JOBS_COLUMNS,
            [
                _job_row(run_id * 10, run_id, "build", "success", labels='["depot-ubuntu-22.04-4"]')
                for run_id in (9400, 9401, 9402, 9403)
            ],
        )
        for result in (
            api.list_pull_requests(team=self.team, author="alice", limit=1),
            api.list_pull_requests(team=self.team, limit=1, offset=1),
        ):
            assert [item.number for item in result.items] == [700070]
            item = result.items[0]
            assert item.ci.passing == 1
            assert item.estimated_cost_usd == pytest.approx(0.032)
            assert item.billable_minutes == pytest.approx(4.0)
            assert item.pushes == 1
            assert [sample.head_sha for sample in item.push_history] == ["old-head"]

    def test_scoped_sources_bound_every_raw_ci_scan(self) -> None:
        self._create_depot_table([_depot_attempt_row()])
        self._create_table("github_pull_requests", PULL_REQUESTS_COLUMNS, [_pr_row(62, "alice", "open", 0, _ago(1))])
        self._create_table(
            "github_workflow_runs",
            WORKFLOW_RUNS_COLUMNS,
            [_run_row(9200, "CI", "sha62", "completed", "success", _ago(1), _ago(1))],
        )
        self._create_table("github_workflow_jobs", WORKFLOW_JOBS_COLUMNS, [_job_row(92001, 9200, "build", "success")])
        curated = CuratedGitHubSource.for_team(self.team)
        depot = curated._depot_job_attempts()
        assert depot is not None and curated._tables.workflow_jobs is not None
        scoped_reads = {
            curated._tables.workflow_runs: "(SELECT * FROM {table} WHERE ((id >= arrayMin(ea_github_run_ids)",
            curated._tables.workflow_jobs: "(SELECT * FROM {table} WHERE ((run_id >= arrayMin(ea_github_run_ids)",
            depot.table: "(SELECT * FROM {table} WHERE run_id IN (SELECT arrayJoin(ea_depot_run_ids))",
        }
        sources = {
            "runs": curated.run_source(live=True, scoped=True),
            "jobs": curated.jobs_source(include_steps=True, scoped=True),
            "job_costs": curated.job_cost_source(scoped=True),
        }
        unscoped = {
            (name, table): sql.count(table) - sql.count(scoped_read.format(table=table))
            for name, sql in sources.items()
            if sql is not None
            for table, scoped_read in scoped_reads.items()
            if sql.count(table) != sql.count(scoped_read.format(table=table))
        }
        assert not unscoped, "A scoped source reads a raw CI table outside its run scope, so it scans all history."
