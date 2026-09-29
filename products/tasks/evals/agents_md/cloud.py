"""Run a trap task as a PostHog Code cloud task, for models that only the cloud product can reach.

The LLM gateway serves the open models in PostHog Code only to credentials that the product itself
issues, so the harness cannot call them from a local CLI. A cloud task gets such a credential.
"""

import json
import time
import hashlib
import secrets
import threading
from pathlib import Path
from typing import Literal, Protocol

import requests

from posthog.dataclasses import frozen

from products.tasks.evals.golden_prs.agents import AgentOutcome

from .workspace import apply_diff, delete_branch, fetch_branch_diff, orphan_commit_with_agents_md, push_commit

CloudRuntime = Literal["posthog-code"]
CLOUD_RUNTIME: CloudRuntime = "posthog-code"
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
POLL_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 60

# Neutral names, because the agent sees both branches and a name that says "eval" or names the
# rule could change what it does.
BRANCH_PREFIX = "posthog/scratch-"

# The Tasks API returns no diff, so the agent's work only leaves the sandbox as a pushed branch.
PUSH_INSTRUCTION = (
    "\n\nWhen you finish, commit your changes and push them to the branch `{branch}`. Do not open a pull request."
)


@frozen
class RunHandle:
    task_id: str
    run_id: str


class Tasks(Protocol):
    def start(self, *, prompt: str, repository: str, branch: str, model: str) -> RunHandle: ...
    def run(self, handle: RunHandle) -> dict: ...
    def logs(self, handle: RunHandle) -> str: ...
    def cost(self, handle: RunHandle) -> dict[str, float]: ...
    def cancel(self, handle: RunHandle) -> None: ...


class TasksClient:
    """The Tasks API calls one cloud run needs, authenticated with a personal API key."""

    def __init__(self, host: str, project_id: int, api_key: str, session: requests.Session | None = None) -> None:
        self._tasks_url = f"{host.rstrip('/')}/api/projects/{project_id}/tasks/"
        self._session = session or requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_key}"

    def _call(self, method: str, path: str, body: dict | None = None) -> requests.Response:
        response = self._session.request(method, self._tasks_url + path, json=body, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response

    def start(self, *, prompt: str, repository: str, branch: str, model: str) -> RunHandle:
        task = self._call(
            "POST",
            "",
            {
                "title": prompt.splitlines()[0][:200],
                "description": prompt,
                "repository": repository,
                "runtime_adapter": "claude",
                "model": model,
            },
        ).json()
        started = self._call("POST", f"{task['id']}/run/", {"mode": "background", "branch": branch}).json()
        return RunHandle(task_id=task["id"], run_id=started["latest_run"]["id"])

    def run(self, handle: RunHandle) -> dict:
        return self._call("GET", f"{handle.task_id}/runs/{handle.run_id}/").json()

    def logs(self, handle: RunHandle) -> str:
        return self._call("GET", f"{handle.task_id}/runs/{handle.run_id}/logs").text

    def cost(self, handle: RunHandle) -> dict[str, float]:
        try:
            usage = self._call("GET", f"{handle.task_id}/usage/").json()
        except requests.HTTPError:
            return {}
        return {"total_cost_usd": usage["total_cost_usd"]} if usage.get("total_cost_usd") is not None else {}

    def cancel(self, handle: RunHandle) -> None:
        self._call("POST", f"{handle.task_id}/runs/{handle.run_id}/cancel/")


def reply_from_log(log: str) -> str:
    """The agent's last message in a run log, which a rule that asks for a warning is judged on."""
    messages = []
    for line in log.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        update = ((entry.get("notification") or {}).get("params") or {}).get("update") or {}
        if update.get("sessionUpdate") != "agent_message":
            continue
        content = update.get("content")
        blocks = content if isinstance(content, list) else [content]
        messages.append("".join(block.get("text", "") for block in blocks if isinstance(block, dict)))
    return messages[-1] if messages else ""


class CloudAgent:
    """Runs jobs as cloud tasks on one base branch per AGENTS.md variant, and removes every branch it pushed."""

    def __init__(self, tasks: Tasks, repo: Path, ref: str, *, repository: str, remote: str) -> None:
        self._tasks, self._repo, self._ref = tasks, repo, ref
        self._repository, self._remote = repository, remote
        self._bases: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()

    def _base(self, agents_md: str) -> tuple[str, str]:
        key = hashlib.sha256(agents_md.encode()).hexdigest()
        with self._lock:
            if key not in self._bases:
                commit = orphan_commit_with_agents_md(self._repo, self._ref, agents_md)
                branch = BRANCH_PREFIX + secrets.token_hex(6)
                push_commit(self._repo, self._remote, commit, branch)
                self._bases[key] = (branch, commit)
            return self._bases[key]

    def _wait(self, handle: RunHandle, timeout_seconds: float) -> tuple[dict, bool]:
        deadline = time.monotonic() + timeout_seconds
        while True:
            run = self._tasks.run(handle)
            if run.get("status") in TERMINAL_STATUSES:
                return run, False
            if time.monotonic() >= deadline:
                self._tasks.cancel(handle)
                return run, True
            time.sleep(POLL_SECONDS)

    def run(
        self, *, model: str, prompt: str, agents_md: str, workdir: Path, timeout_seconds: float = 30 * 60
    ) -> AgentOutcome:
        """Run one job and apply the agent's pushed change to `workdir`, a checkout of the same tree."""
        base_branch, base = self._base(agents_md)
        work_branch = BRANCH_PREFIX + secrets.token_hex(6)
        started = time.monotonic()
        handle = self._tasks.start(
            prompt=prompt + PUSH_INSTRUCTION.format(branch=work_branch),
            repository=self._repository,
            branch=base_branch,
            model=model,
        )
        run, timed_out = self._wait(handle, timeout_seconds)
        duration = round(time.monotonic() - started, 1)
        try:
            diff = fetch_branch_diff(self._repo, self._remote, work_branch, base)
        finally:
            delete_branch(self._repo, self._remote, work_branch)
        if diff:
            apply_diff(workdir, diff)
        log = self._tasks.logs(handle)
        return AgentOutcome(
            agent_version=f"{CLOUD_RUNTIME} task {handle.task_id} run {handle.run_id}",
            exit_code=0 if run.get("status") == "completed" else 1,
            timed_out=timed_out,
            duration_seconds=duration,
            failure=_failure(run, timed_out, pushed=diff is not None, branch=work_branch),
            reply=reply_from_log(log),
            usage=self._tasks.cost(handle),
            log=log,
        )

    def close(self) -> None:
        with self._lock:
            for branch, _commit in self._bases.values():
                delete_branch(self._repo, self._remote, branch)
            self._bases.clear()


def _failure(run: dict, timed_out: bool, *, pushed: bool, branch: str) -> str | None:
    if timed_out:
        return "The cloud run hit the case timeout."
    if run.get("status") != "completed":
        return run.get("error_message") or f"The cloud run ended as {run.get('status')}."
    if not pushed:
        return f"The agent did not push {branch}, so there is no change to score."
    return None
