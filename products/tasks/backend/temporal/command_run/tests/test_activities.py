import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import ExecutionResult, Sandbox, WorkingTreeChanges
from products.tasks.backend.temporal.command_run.activities import (
    CommitAndOpenPrInput,
    RunCommandInSandboxInput,
    commit_and_open_pr,
    run_command_in_sandbox,
)


class _FakeStream:
    def __init__(self, lines, exit_code):
        self._lines = lines
        self._exit_code = exit_code

    def iter_stdout(self):
        yield from self._lines

    def wait(self):
        return ExecutionResult(stdout="", stderr="", exit_code=self._exit_code)


def _github_mock(mocker, *, branch_sha="base-sha", commit_sha="commit-sha", pr_url="https://github.com/o/r/pull/3"):
    github = mocker.Mock()
    github.access_token_expired.return_value = False
    github.get_default_branch.return_value = "main"
    github.create_branch.return_value = {"success": True, "sha": branch_sha}
    github.create_signed_commit.return_value = {"success": True, "commit_sha": commit_sha}
    github.create_pull_request.return_value = {"success": True, "pr_url": pr_url}
    mocker.patch(
        "products.tasks.backend.temporal.command_run.activities.Integration.objects.get", return_value=mocker.Mock()
    )
    mocker.patch("products.tasks.backend.temporal.command_run.activities.GitHubIntegration", return_value=github)
    return github


def _commit_input() -> CommitAndOpenPrInput:
    return CommitAndOpenPrInput(
        run_id="run-1",
        sandbox_id="sandbox-1",
        repository="posthog/hedgebox",
        github_integration_id=1,
        branch="cloud-run/run-1",
        commit_message="msg",
        pr_title="title",
        pr_body="body",
        base_branch=None,
    )


@pytest.mark.django_db
def test_run_command_in_sandbox_cds_into_repo_and_returns_exit_code(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-1")
    sandbox.execute_stream.return_value = _FakeStream(["hello\n"], 0)
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)

    result = async_to_sync(activity_environment.run)(
        run_command_in_sandbox,
        RunCommandInSandboxInput(
            run_id="run-1", sandbox_id="sandbox-1", command="echo hi", repository="PostHog/Hedgebox"
        ),
    )

    assert result.exit_code == 0
    assert sandbox.execute_stream.call_args.args[0] == "cd /tmp/workspace/repos/posthog/hedgebox && echo hi"


@pytest.mark.django_db
def test_commit_and_open_pr_skips_pr_when_repo_clean(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-1")
    sandbox.is_git_clean.return_value = (True, "")
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    _github_mock(mocker)
    update_output = mocker.patch("products.tasks.backend.temporal.command_run.activities.TaskRun.update_output_atomic")

    result = async_to_sync(activity_environment.run)(commit_and_open_pr, _commit_input())

    assert result.created_pr is False
    assert result.pr_url is None
    sandbox.stage_and_collect_changes.assert_not_called()
    update_output.assert_not_called()


@pytest.mark.django_db
def test_commit_and_open_pr_creates_signed_commit_and_records_output(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-1")
    sandbox.is_git_clean.return_value = (False, " M README.md")
    sandbox.stage_and_collect_changes.return_value = WorkingTreeChanges(
        additions=[("README.md", "YmFzZTY0")], deletions=[]
    )
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    github = _github_mock(mocker)
    update_output = mocker.patch("products.tasks.backend.temporal.command_run.activities.TaskRun.update_output_atomic")

    result = async_to_sync(activity_environment.run)(commit_and_open_pr, _commit_input())

    assert result.created_pr is True
    assert result.pr_url == "https://github.com/o/r/pull/3"
    assert result.commit_sha == "commit-sha"
    # Bare repo name (org resolved from the integration), branched from the default branch.
    assert github.create_branch.call_args.args == ("hedgebox", "cloud-run/run-1", "main")
    commit_kwargs = github.create_signed_commit.call_args.kwargs
    assert commit_kwargs["expected_head_oid"] == "base-sha"
    assert commit_kwargs["additions"] == [("README.md", "YmFzZTY0")]
    update_output.assert_called_once_with(
        "run-1", {"pr_url": "https://github.com/o/r/pull/3", "commit_sha": "commit-sha"}
    )


@pytest.mark.django_db
def test_commit_and_open_pr_raises_when_signed_commit_fails(activity_environment, mocker):
    sandbox = mocker.Mock(id="sandbox-1")
    sandbox.is_git_clean.return_value = (False, " M README.md")
    sandbox.stage_and_collect_changes.return_value = WorkingTreeChanges(
        additions=[("README.md", "YmFzZTY0")], deletions=[]
    )
    mocker.patch.object(Sandbox, "get_by_id", return_value=sandbox)
    github = _github_mock(mocker)
    github.create_signed_commit.return_value = {"success": False, "error": "stale head"}

    with pytest.raises(RuntimeError, match="Failed to create signed commit"):
        async_to_sync(activity_environment.run)(commit_and_open_pr, _commit_input())
