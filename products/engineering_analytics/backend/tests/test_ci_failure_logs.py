from types import SimpleNamespace

from unittest import mock

from products.engineering_analytics.backend.facade.contracts import RepoRef, WorkflowRunDetail
from products.engineering_analytics.backend.logic.queries import ci_failure_logs as module


def _run(run_id: int) -> WorkflowRunDetail:
    return WorkflowRunDetail(
        repo=RepoRef(provider="github", owner="o", name="r"),
        id=run_id,
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
    )


# Rows mimic the logs query output, ordered by (run_id, job_id, seq):
# (run_id, job_id, conclusion, branch, orig_total, orig_line, body)
def _query(rows, runs):
    curated = mock.Mock()
    curated.run.return_value = SimpleNamespace(results=rows)
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
