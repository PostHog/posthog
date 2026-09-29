import json
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from parameterized import parameterized

from products.tasks.evals.agents_md.cloud import CloudAgent, RunHandle, TasksClient, reply_from_log
from products.tasks.evals.agents_md.workspace import checkout_with_agents_md


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def commit_all(cwd: Path, message: str) -> str:
    git(cwd, "add", "-A")
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[tuple[Path, Path, str]]:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    local = tmp_path / "local"
    local.mkdir()
    git(local, "init", "-q")
    (local / "AGENTS.md").write_text("- rule one\n- rule two\n")
    (local / "CLAUDE.md").symlink_to("AGENTS.md")
    (local / "app.py").write_text("x = 1\n")
    commit_all(local, "history that names rule two")
    git(local, "remote", "add", "origin", str(remote))
    yield local, remote, git(local, "rev-parse", "HEAD")


def agent_log(*texts: str) -> str:
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
    return "\n".join(json.dumps(line) for line in lines)


class FakeTasks:
    """Stands in for the Tasks API, and plays the sandbox agent by pushing to the branch the prompt names."""

    def __init__(self, remote: Path, work: Path, agent: Callable[[Path], None] | None, status: str = "completed"):
        self.remote, self.work, self.agent, self.status = remote, work, agent, status
        self.started: dict = {}

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
        return {"status": self.status, "error_message": "sandbox died" if self.status == "failed" else None}

    def logs(self, handle: RunHandle) -> str:
        return agent_log("Working on it.", "Done. I changed app.py.")

    def cost(self, handle: RunHandle) -> dict[str, float]:
        return {"total_cost_usd": 0.25}

    def cancel(self, handle: RunHandle) -> None:
        pass


def edit_app(clone: Path) -> None:
    (clone / "app.py").write_text("x = 2\n")


@pytest.mark.parametrize(
    "agent,status,failure,change",
    [
        pytest.param(edit_app, "completed", None, "+x = 2", id="pushed work"),
        pytest.param(None, "completed", "The agent did not push", "", id="pushed nothing"),
        pytest.param(edit_app, "failed", "sandbox died", "+x = 2", id="run failed"),
    ],
)
def test_cloud_run_brings_the_agent_work_into_the_local_checkout(
    agent: Callable[[Path], None] | None,
    status: str,
    failure: str | None,
    change: str,
    repo: tuple[Path, Path, str],
    tmp_path: Path,
) -> None:
    local, remote, ref = repo
    tasks = FakeTasks(remote, tmp_path, agent, status)
    cloud = CloudAgent(tasks, local, ref, repository="PostHog/posthog", remote="origin")
    with checkout_with_agents_md(local, ref, "- rule one\n") as workdir:
        outcome = cloud.run(model="zai-org/glm-5.3", prompt="Change app.py.", agents_md="- rule one\n", workdir=workdir)
        applied = git(workdir, "diff")
    cloud.close()

    assert (outcome.failure or "").startswith(failure or "") and (failure is None) == (outcome.failure is None)
    assert change in applied
    assert outcome.reply == "Done. I changed app.py."
    assert outcome.usage == {"total_cost_usd": 0.25}
    assert tasks.started["model"] == "zai-org/glm-5.3"
    assert git(local, "ls-remote", "--heads", "origin") == ""


def test_cloud_base_holds_the_arm_instructions_and_no_history(repo: tuple[Path, Path, str], tmp_path: Path) -> None:
    local, remote, ref = repo
    tasks = FakeTasks(remote, tmp_path, None)
    cloud = CloudAgent(tasks, local, ref, repository="PostHog/posthog", remote="origin")
    with checkout_with_agents_md(local, ref, "- rule one\n") as workdir:
        cloud.run(model="m", prompt="p", agents_md="- rule one\n", workdir=workdir)
        base = git(local, "ls-remote", "origin", tasks.started["branch"]).split()[0]

        assert git(local, "log", "-1", "--format=%P", base) == ""
        assert git(local, "show", f"{base}:AGENTS.md") == "- rule one"
        assert git(local, "diff", "--name-only", ref, base) == "AGENTS.md"
    cloud.close()
    assert git(local, "ls-remote", "--heads", "origin") == ""


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


def test_client_creates_a_claude_task_and_starts_it_in_the_background_on_the_base_branch() -> None:
    calls: list[tuple[str, str, dict | None]] = []

    class Session:
        headers: dict[str, str] = {}

        def request(self, method: str, url: str, json: dict | None = None, timeout: float = 0) -> "Response":
            calls.append((method, url, json))
            return Response({"id": "task-1"} if url.endswith("/tasks/") else {"latest_run": {"id": "run-1"}})

    class Response:
        def __init__(self, body: dict) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self.body

    client = TasksClient("https://us.posthog.com", 2, "phx_fake", session=Session())
    handle = client.start(prompt="Do it.", repository="PostHog/posthog", branch="base", model="moonshotai/kimi-k3")

    assert handle == RunHandle(task_id="task-1", run_id="run-1")
    (_, create_url, create), (_, run_url, run) = calls
    assert create_url == "https://us.posthog.com/api/projects/2/tasks/"
    assert create == {
        "title": "Do it.",
        "description": "Do it.",
        "repository": "PostHog/posthog",
        "runtime_adapter": "claude",
        "model": "moonshotai/kimi-k3",
    }
    assert run_url == "https://us.posthog.com/api/projects/2/tasks/task-1/run/"
    assert run == {"mode": "background", "branch": "base"}
