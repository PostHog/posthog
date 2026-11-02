import json
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.engineering_analytics.backend.facade.contracts import CIEngine, RepoRef, WorkflowRunDetail
from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME
from products.engineering_analytics.backend.logic.queries import ci_failure_logs as module
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.sources import GitHubTables


def _run(run_id: int) -> WorkflowRunDetail:
    return WorkflowRunDetail(
        repo=RepoRef(provider="github", owner="o", name="r"),
        id=run_id,
        ci_engine=CIEngine.GITHUB_ACTIONS,
        workflow_name="CI",
        head_sha="sha",
        head_branch="main",
        status="completed",
        conclusion="failure",
        run_started_at=None,
        updated_at=None,
        duration_seconds=None,
        run_attempt=1,
        pr_number=5,
        commit_pr_number=None,
        is_merge_queue=False,
    )


# Rows mimic the logs query output, ordered by (run_id, job_id, seq):
# (run_id, job_id, conclusion, branch, orig_total, orig_line, body)
def _query(rows, runs):
    curated = mock.Mock()
    curated.run.return_value = SimpleNamespace(results=[(*row, "") if len(row) == 7 else row for row in rows])
    with mock.patch.object(module, "query_pr_runs", return_value=runs):
        return module.query_ci_failure_logs(curated=curated, pr_number=5, repo_owner="o", repo_name="r"), curated


def test_groups_by_job_and_anchors_each_line_to_its_original_position():
    # The whole point of the endpoint: failures grouped per job, each line keeping its 1-based original
    # line number (markers → None), so an agent can locate the failure in the full log. A regression in
    # grouping, the orig_line/orig_total mapping, or the marker handling would surface here.
    rows = [
        ("100", "9", "failure", "main", "5000", "1", "first"),
        ("100", "9", "failure", "main", "5000", "", "... 4810 lines omitted ..."),
        ("100", "9", "failure", "main", "5000", "4812", "##[error]boom"),
        ("100", "10", "timed_out", "main", "200", "7", "slow step"),
    ]
    result, _ = _query(rows, [_run(100)])

    assert result.runs_attributed == 1
    assert result.logs_available is True
    assert [job.job_id for job in result.jobs] == [9, 10]

    job9 = result.jobs[0]
    assert (job9.conclusion, job9.original_total_lines) == ("failure", 5000)
    assert [(line.original_line, line.text) for line in job9.lines] == [
        (1, "first"),
        (None, "... 4810 lines omitted ..."),
        (4812, "##[error]boom"),
    ]
    assert result.jobs[1].conclusion == "timed_out"


def test_no_attributed_runs_short_circuits_without_querying_logs():
    # A fork PR (no pull_requests association) or a PR with no CI resolves to zero runs — return
    # unavailable and never touch the logs cluster, rather than running an empty IN () query.
    result, curated = _query(rows=[], runs=[])
    assert (result.runs_attributed, result.logs_available, result.jobs) == (0, False, [])
    curated.run.assert_not_called()


def test_colliding_engine_job_ids_keep_failure_lines_separate():
    rows = [
        ("100", "9", "failure", "main", "20", "1", "Depot failure", "depot_ci"),
        ("100", "9", "failure", "main", "30", "2", "GitHub failure", "github_actions"),
    ]
    result, _ = _query(rows, [_run(100)])
    assert [(job.ci_engine, [line.text for line in job.lines]) for job in result.jobs] == [
        (CIEngine.DEPOT_CI, ["Depot failure"]),
        (CIEngine.GITHUB_ACTIONS, ["GitHub failure"]),
    ]


def test_per_job_lines_are_capped(monkeypatch):
    # One noisy job must not blow the per-job cap; the excess is dropped and truncated flags it.
    monkeypatch.setattr(module, "_PER_JOB_CAP", 2)
    rows = [("100", "9", "failure", "main", "9", str(i + 1), f"line{i}") for i in range(5)]
    result, _ = _query(rows, [_run(100)])

    job = result.jobs[0]
    assert job.line_count == 2
    assert len(job.lines) == 2
    assert job.truncated is True


def test_overall_cap_flags_the_clipped_tail_job(monkeypatch):
    # When the overall cap clips mid-job, that tail job's lines are an undercount, not a complete log —
    # it must read truncated so a consumer isn't misled into thinking it has the whole failure.
    monkeypatch.setattr(module, "_LINE_CAP", 3)
    rows = [
        ("200", "9", "failure", "main", "10", "1", "a1"),
        ("200", "9", "failure", "main", "10", "2", "a2"),
        ("100", "8", "failure", "main", "10", "1", "b1"),  # only line of job 8 that survives the cap
        ("100", "8", "failure", "main", "10", "2", "b2"),  # dropped by the overall cap
    ]
    result, _ = _query(rows, [_run(200), _run(100)])

    assert result.truncated is True
    assert [job.job_id for job in result.jobs] == [9, 8]
    assert result.jobs[0].truncated is False  # job 9 is whole, within the cap
    assert result.jobs[-1].truncated is True  # job 8 was clipped by the overall cap


class TestRunFailureLogsOverClickHouse(ClickhouseTestMixin, BaseTest):
    def _failure_log(self, *, body: str, seq: int, ci_engine: str | None) -> dict[str, Any]:
        # attributes_map_str keys carry the "__str" suffix the logs table strips for the queryable map.
        attributes = {
            "repo__str": "o/r",
            "run_id__str": "100",
            "job_id__str": "9",
            "conclusion__str": "failure",
            "seq__str": str(seq),
        }
        if ci_engine is not None:
            attributes["ci_engine__str"] = ci_engine
        return {
            "team_id": self.team.id,
            "timestamp": "2026-07-10 12:00:00.000000",
            "body": body,
            "service_name": CI_LOGS_SERVICE_NAME,
            "attributes_map_str": attributes,
        }

    @parameterized.expand([("legacy_line_without_engine", None), ("stamped_line", "github_actions")])
    def test_returns_lines_for_a_github_actions_run(self, _name: str, ci_engine: str | None) -> None:
        row = self._failure_log(body="FAILED test_x", seq=0, ci_engine=ci_engine)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{json.dumps(row)}\n")
        curated = CuratedGitHubSource(
            team=self.team,
            tables=GitHubTables(pull_requests="unused", workflow_runs="unused", workflow_jobs=None, repository="o/r"),
        )
        # The run lookups read the warehouse; this test covers only the logs read.
        with (
            mock.patch.object(module, "query_workflow_run", return_value=_run(100)),
            mock.patch.object(module, "_legacy_run_ids", return_value=["100"]),
        ):
            result = module.query_run_failure_logs(curated=curated, run_id=100, ci_engine=CIEngine.GITHUB_ACTIONS)

        assert result.logs_available is True
        assert [[line.text for line in job.lines] for job in result.jobs] == [["FAILED test_x"]]
