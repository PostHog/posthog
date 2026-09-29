import json
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest

import requests
from parameterized import parameterized

from products.tasks.evals.agents_md.cloud import (
    CloudAgent,
    RunHandle,
    RunnerStopped,
    TasksClient,
    clean_up,
    reply_from_log,
)
from products.tasks.evals.agents_md.workspace import checkout_with_agents_md


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def commit_all(cwd: Path, message: str) -> str:
    git(cwd, "add", "-A")
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--no-gpg-sign", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[tuple[Path, Path, str]]:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    local = tmp_path / "local"
    local.mkdir()
    git(local, "init", "-q")
    git(local, "config", "user.name", "t")
    git(local, "config", "user.email", "t@example.com")
    git(local, "config", "commit.gpgsign", "false")
    (local / "AGENTS.md").write_text("- rule one\n- rule two\n")
    (local / "CLAUDE.md").symlink_to("AGENTS.md")
    (local / "app.py").write_text("x = 1\n")
    commit_all(local, "history that names rule two")
    git(local, "remote", "add", "origin", str(remote))
    yield local, remote, git(local, "rev-parse", "HEAD")


def agent_log(*texts: str, turn_done: bool = True) -> str:
    lines = [{"type": "notification", "notification": {"method": "session/update", "params": {"update": {}}}}]
    lines += [
        {
            "type": "notification",
            "notification": {
                "method": "session/update",
                "params": {"update": {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}}},
            },
        }
        for text in texts
    ]
    if turn_done:
        lines.append({"type": "notification", "notification": {"method": "_posthog/turn_complete", "params": {}}})
    return "\n".join(json.dumps(line) for line in lines)


class FakeTasks:
    """Stands in for the Tasks API, and plays the sandbox agent by pushing to the branch the prompt names."""

    def __init__(self, remote: Path, work: Path, agent: Callable[[Path], None] | None, status: str = "completed"):
        self.remote, self.work, self.agent, self.status = remote, work, agent, status
        self.started: dict = {}
        self.cancelled = False
        self.on_poll: Callable[[], None] | None = None

    def start(self, *, prompt: str, repository: str, branch: str, model: str) -> RunHandle:
        self.started = {"prompt": prompt, "repository": repository, "branch": branch, "model": model}
        if self.agent:
            push_to = prompt.split("`")[-2]
            clone = self.work / "sandbox"
            git(self.work, "clone", "-q", "--branch", branch, str(self.remote), str(clone))
            self.agent(clone)
            commit_all(clone, "agent work")
            git(clone, "push", "-q", "origin", f"HEAD:refs/heads/{push_to}")
        return RunHandle(task_id="task", run_id="run")

    def run(self, handle: RunHandle) -> dict:
        if self.on_poll:
            self.on_poll()
        return {"status": self.status, "error_message": "sandbox died" if self.status == "failed" else None}

    def logs(self, handle: RunHandle) -> str:
        return agent_log("Working on it.", "Done. I changed app.py.", turn_done=self.on_poll is None)

    def cost(self, handle: RunHandle) -> dict[str, float]:
        return {"total_cost_usd": 0.25}

    def cancel(self, handle: RunHandle) -> None:
        self.cancelled = True


def edit_app(clone: Path) -> None:
    (clone / "app.py").write_text("x = 2\n")


def cloud_agent(tasks: FakeTasks, local: Path, ref: str, tmp_path: Path) -> CloudAgent:
    return CloudAgent(
        tasks, local, ref, repository="PostHog/posthog", remote="origin", ledger=tmp_path / "cloud-ledger.jsonl"
    )


@pytest.mark.parametrize(
    "agent,status,stop_while_waiting,failure,change",
    [
        pytest.param(edit_app, "completed", False, None, "+x = 2", id="pushed work"),
        pytest.param(edit_app, "in_progress", False, None, "+x = 2", id="turn ended but the run waits for a reply"),
        pytest.param(None, "completed", False, "The agent did not push", "", id="pushed nothing"),
        pytest.param(edit_app, "failed", False, "sandbox died", "+x = 2", id="run failed"),
        pytest.param(edit_app, "in_progress", True, "The runner stopped", "+x = 2", id="runner stopped mid-turn"),
    ],
)
def test_cloud_run_brings_the_agent_work_into_the_local_checkout(
    agent: Callable[[Path], None] | None,
    status: str,
    stop_while_waiting: bool,
    failure: str | None,
    change: str,
    repo: tuple[Path, Path, str],
    tmp_path: Path,
) -> None:
    local, remote, ref = repo
    tasks = FakeTasks(remote, tmp_path, agent, status)
    cloud = cloud_agent(tasks, local, ref, tmp_path)
    if stop_while_waiting:
        tasks.on_poll = cloud.stop
    with checkout_with_agents_md(local, ref, "- rule one\n") as workdir:
        outcome = cloud.run(model="zai-org/glm-5.3", prompt="Change app.py.", agents_md="- rule one\n", workdir=workdir)
        applied = git(workdir, "diff")
    cloud.close()

    assert (outcome.failure or "").startswith(failure or "") and (failure is None) == (outcome.failure is None)
    assert change in applied
    assert outcome.reply == "Done. I changed app.py."
    assert outcome.usage == {"total_cost_usd": 0.25}
    assert tasks.started["model"] == "zai-org/glm-5.3"
    assert tasks.cancelled == (status == "in_progress")
    assert git(local, "ls-remote", "--heads", "origin") == ""


def test_cloud_base_holds_the_arm_instructions_and_no_history(repo: tuple[Path, Path, str], tmp_path: Path) -> None:
    local, remote, ref = repo
    tasks = FakeTasks(remote, tmp_path, None)
    cloud = cloud_agent(tasks, local, ref, tmp_path)
    with checkout_with_agents_md(local, ref, "- rule one\n") as workdir:
        cloud.run(model="m", prompt="p", agents_md="- rule one\n", workdir=workdir)
        base = git(local, "ls-remote", "origin", tasks.started["branch"]).split()[0]

        assert git(local, "log", "-1", "--format=%P", base) == ""
        assert git(local, "show", f"{base}:AGENTS.md") == "- rule one"
        assert git(local, "diff", "--name-only", ref, base) == "AGENTS.md"
    cloud.close()
    assert git(local, "ls-remote", "--heads", "origin") == ""


def test_a_stopped_runner_starts_no_more_tasks(repo: tuple[Path, Path, str], tmp_path: Path) -> None:
    local, remote, ref = repo
    tasks = FakeTasks(remote, tmp_path, edit_app)
    cloud = cloud_agent(tasks, local, ref, tmp_path)
    cloud.stop()
    with checkout_with_agents_md(local, ref, "- rule one\n") as workdir, pytest.raises(RunnerStopped):
        cloud.run(model="m", prompt="p", agents_md="- rule one\n", workdir=workdir)

    assert tasks.started == {}
    assert git(local, "ls-remote", "--heads", "origin") == ""


class CrashingTasks(FakeTasks):
    crashing = True

    def run(self, handle: RunHandle) -> dict:
        if self.crashing:
            raise ConnectionError("runner lost")
        return super().run(handle)


def test_clean_up_after_a_crash_cancels_the_open_run_and_deletes_every_branch(
    repo: tuple[Path, Path, str], tmp_path: Path
) -> None:
    local, remote, ref = repo
    tasks = CrashingTasks(remote, tmp_path, edit_app, status="in_progress")
    with checkout_with_agents_md(local, ref, "- rule one\n") as workdir, pytest.raises(ConnectionError):
        cloud_agent(tasks, local, ref, tmp_path).run(model="m", prompt="p", agents_md="- rule one\n", workdir=workdir)
    git(local, "push", "-q", "origin", f"{ref}:refs/heads/posthog/scratch-not-in-the-ledger")

    tasks.crashing = False
    clean_up(tmp_path / "cloud-ledger.jsonl", tasks, local, "origin")

    assert tasks.cancelled
    assert git(local, "ls-remote", "--heads", "origin").split()[1:] == ["refs/heads/posthog/scratch-not-in-the-ledger"]


@parameterized.expand(
    [
        ("last message wins", agent_log("First.", "Last."), "Last."),
        ("no message", agent_log(), ""),
        (
            "content as a list",
            agent_log().replace(
                "{}", '{"sessionUpdate": "agent_message", "content": [{"type": "text", "text": "Listed."}]}'
            ),
            "Listed.",
        ),
    ]
)
def test_reply_is_the_agent_last_message(_name: str, log: str, expected: str) -> None:
    assert reply_from_log(log) == expected


class FakeSession:
    """Answers the create call with a task and the run call with a run of `run_model`."""

    headers: dict[str, str] = {}

    def __init__(self, run_model: str) -> None:
        self.run_model = run_model
        self.calls: list[tuple[str, dict | None]] = []

    def request(self, method: str, url: str, json: dict | None = None, timeout: float = 0) -> "FakeResponse":
        self.calls.append((url, json))
        if url.endswith("/tasks/"):
            return FakeResponse({"id": "task-1"})
        return FakeResponse({"latest_run": {"id": "run-1", "model": self.run_model}})


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.body


def start_kimi(session: FakeSession) -> RunHandle:
    client = TasksClient("https://us.posthog.com", 2, "phx_fake", session=cast(requests.Session, session))
    return client.start(prompt="Do it.", repository="PostHog/posthog", branch="base", model="moonshotai/kimi-k3")


def test_client_starts_a_background_claude_run_of_the_chosen_model_on_the_base_branch() -> None:
    session = FakeSession("moonshotai/kimi-k3")

    assert start_kimi(session) == RunHandle(task_id="task-1", run_id="run-1")
    assert session.calls == [
        (
            "https://us.posthog.com/api/projects/2/tasks/",
            {"title": "Do it.", "description": "Do it.", "repository": "PostHog/posthog"},
        ),
        (
            "https://us.posthog.com/api/projects/2/tasks/task-1/run/",
            {"mode": "background", "branch": "base", "runtime_adapter": "claude", "model": "moonshotai/kimi-k3"},
        ),
    ]


def test_client_refuses_a_run_of_another_model() -> None:
    with pytest.raises(RuntimeError, match="runs claude-opus-5-5, not moonshotai/kimi-k3"):
        start_kimi(FakeSession("claude-opus-5-5"))
