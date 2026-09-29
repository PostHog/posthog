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

from .workspace import (
    apply_diff,
    delete_branches,
    fetch_branch_diff,
    orphan_commit_with_agents_md,
    push_commit,
    remote_branches,
)

CloudRuntime = Literal["posthog-code"]
CLOUD_RUNTIME: CloudRuntime = "posthog-code"
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
POLL_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 60
CLOUD_LEDGER = "cloud-ledger.jsonl"
TIMED_OUT = "The cloud run hit the case timeout."
STOPPED = "The runner stopped before the run ended."

# Neutral names, because the agent sees both branches and a name that says "eval" or names the
# rule could change what it does.
BRANCH_PREFIX = "posthog/scratch-"

# The Tasks API returns no diff, so the agent's work only leaves the sandbox as a pushed branch.
PUSH_INSTRUCTION = (
    "\n\nWhen you finish, commit your changes and push them to the branch `{branch}`. Do not open a pull request."
)


class RunnerStopped(Exception):
    pass


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
            {"title": prompt.splitlines()[0][:200], "description": prompt, "repository": repository},
        ).json()
        # The run, not the task, holds the model; a model sent on the task is dropped.
        run = self._call(
            "POST",
            f"{task['id']}/run/",
            {"mode": "background", "branch": branch, "runtime_adapter": "claude", "model": model},
        ).json()["latest_run"]
        if run.get("model") != model:
            raise RuntimeError(f"Task {task['id']} runs {run.get('model')}, not {model}.")
        return RunHandle(task_id=task["id"], run_id=run["id"])

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


def _log_entries(log: str) -> list[dict]:
    entries = []
    for line in log.splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def turn_completed(log: str) -> bool:
    return any(
        (entry.get("notification") or {}).get("method") == "_posthog/turn_complete" for entry in _log_entries(log)
    )


def reply_from_log(log: str) -> str:
    """The agent's last message in a run log, which a rule that asks for a warning is judged on."""
    messages = []
    for entry in _log_entries(log):
        update = ((entry.get("notification") or {}).get("params") or {}).get("update") or {}
        if update.get("sessionUpdate") != "agent_message":
            continue
        content = update.get("content")
        blocks = content if isinstance(content, list) else [content]
        messages.append("".join(block.get("text", "") for block in blocks if isinstance(block, dict)))
    return messages[-1] if messages else ""


def clean_up(ledger: Path, tasks: Tasks, repo: Path, remote: str) -> None:
    """Delete the branches in `ledger` that are still on `remote`, and cancel its runs that are still open.

    A runner that crashes, or loses the key agent it pushes with, cannot do this itself.
    """
    entries = _log_entries(ledger.read_text()) if ledger.exists() else []
    recorded = {entry["branch"] for entry in entries if "branch" in entry}
    delete_branches(repo, remote, *sorted(recorded & remote_branches(repo, remote, BRANCH_PREFIX)))
    for entry in entries:
        if "run_id" in entry:
            handle = RunHandle(task_id=entry["task_id"], run_id=entry["run_id"])
            if tasks.run(handle).get("status") not in TERMINAL_STATUSES:
                tasks.cancel(handle)


class CloudAgent:
    """Runs jobs as cloud tasks on one base branch per AGENTS.md variant, and removes every branch it pushed.

    It records each branch and run in `ledger` before it can leave one behind, for `clean_up`.
    """

    def __init__(self, tasks: Tasks, repo: Path, ref: str, *, repository: str, remote: str, ledger: Path) -> None:
        self._tasks, self._repo, self._ref = tasks, repo, ref
        self._repository, self._remote, self._ledger = repository, remote, ledger
        self._bases: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()
        self._ledger_lock = threading.Lock()
        self._stopping = threading.Event()

    def _record(self, **entry: str) -> None:
        with self._ledger_lock, self._ledger.open("a") as ledger:
            ledger.write(json.dumps(entry) + "\n")

    def _base(self, agents_md: str) -> tuple[str, str]:
        key = hashlib.sha256(agents_md.encode()).hexdigest()
        with self._lock:
            if key not in self._bases:
                commit = orphan_commit_with_agents_md(self._repo, self._ref, agents_md)
                branch = BRANCH_PREFIX + secrets.token_hex(6)
                self._record(branch=branch)
                push_commit(self._repo, self._remote, commit, branch)
                self._bases[key] = (branch, commit)
            return self._bases[key]

    def _wait(self, handle: RunHandle, timeout_seconds: float) -> tuple[dict, str, str | None]:
        """Wait for the agent's turn to end, then stop the run. Also returns why the wait ended early, if it did.

        A background run stays in progress after the turn, with its sandbox up, waiting for a
        follow-up message that never comes.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            run, log = self._tasks.run(handle), self._tasks.logs(handle)
            if run.get("status") in TERMINAL_STATUSES or turn_completed(log):
                cut_short = None
                break
            if self._stopping.is_set():
                cut_short = STOPPED
                break
            if time.monotonic() >= deadline:
                cut_short = TIMED_OUT
                break
            self._stopping.wait(POLL_SECONDS)
        if run.get("status") not in TERMINAL_STATUSES:
            self._tasks.cancel(handle)
        return run, log, cut_short

    def run(
        self, *, model: str, prompt: str, agents_md: str, workdir: Path, timeout_seconds: float = 30 * 60
    ) -> AgentOutcome:
        """Run one job and apply the agent's pushed change to `workdir`, a checkout of the same tree."""
        if self._stopping.is_set():
            raise RunnerStopped("The runner is stopping, so it starts no more tasks.")
        base_branch, base = self._base(agents_md)
        work_branch = BRANCH_PREFIX + secrets.token_hex(6)
        self._record(branch=work_branch)
        started = time.monotonic()
        handle = self._tasks.start(
            prompt=prompt + PUSH_INSTRUCTION.format(branch=work_branch),
            repository=self._repository,
            branch=base_branch,
            model=model,
        )
        self._record(task_id=handle.task_id, run_id=handle.run_id)
        run, log, cut_short = self._wait(handle, timeout_seconds)
        duration = round(time.monotonic() - started, 1)
        try:
            diff = fetch_branch_diff(self._repo, self._remote, work_branch, base)
        finally:
            delete_branches(self._repo, self._remote, work_branch)
        if diff:
            apply_diff(workdir, diff)
        failure = cut_short or _failure(run, pushed=diff is not None, branch=work_branch)
        return AgentOutcome(
            agent_version=f"{CLOUD_RUNTIME} task {handle.task_id} run {handle.run_id}",
            exit_code=0 if failure is None else 1,
            timed_out=cut_short == TIMED_OUT,
            duration_seconds=duration,
            failure=failure,
            reply=reply_from_log(log),
            usage=self._tasks.cost(handle),
            log=log,
        )

    def stop(self) -> None:
        """Cut each wait short, cancelling its run, and refuse jobs that have not started."""
        self._stopping.set()

    def close(self) -> None:
        clean_up(self._ledger, self._tasks, self._repo, self._remote)


def _failure(run: dict, *, pushed: bool, branch: str) -> str | None:
    if run.get("status") in ("failed", "cancelled"):
        return run.get("error_message") or f"The cloud run ended as {run.get('status')}."
    if not pushed:
        return f"The agent did not push {branch}, so there is no change to score."
    return None
