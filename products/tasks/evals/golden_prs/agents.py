import os
import json
import time
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Runtime = Literal["claude", "codex"]

DEFAULT_MODELS: dict[Runtime, str] = {"claude": "claude-opus-5", "codex": "gpt-5.5"}

# The agent must reproduce the PR from the description alone, so it gets no GitHub credentials.
GITHUB_CREDENTIAL_VARS = ("GH_TOKEN", "GITHUB_TOKEN")

# The judge's provider key stays in the parent process; an unsandboxed agent has no use for the other runtime's key.
OTHER_PROVIDER_KEYS: dict[Runtime, str] = {"claude": "OPENAI_API_KEY", "codex": "ANTHROPIC_API_KEY"}


@dataclass(frozen=True, kw_only=True, slots=True)
class AgentRun:
    runtime: Runtime
    model: str
    agent_version: str
    exit_code: int
    timed_out: bool
    duration_seconds: float
    stdout: str
    stderr: str


def agent_command(runtime: Runtime, model: str) -> list[str]:
    if runtime == "claude":
        return ["claude", "-p", "--model", model, "--dangerously-skip-permissions", "--output-format", "json"]
    return ["codex", "exec", "--model", model, "--dangerously-bypass-approvals-and-sandbox", "--json", "-"]


def agent_environment(env: Mapping[str, str], runtime: Runtime) -> dict[str, str]:
    dropped = (*GITHUB_CREDENTIAL_VARS, OTHER_PROVIDER_KEYS[runtime])
    return {key: value for key, value in env.items() if key not in dropped}


AGENT_VERSION_TIMEOUT_SECONDS = 30


def agent_version(runtime: Runtime) -> str:
    return subprocess.run(
        [runtime, "--version"], capture_output=True, text=True, check=True, timeout=AGENT_VERSION_TIMEOUT_SECONDS
    ).stdout.strip()


def _claude_report(run: AgentRun) -> dict:
    if run.runtime != "claude":
        return {}
    try:
        return json.loads(run.stdout)
    except json.JSONDecodeError:
        return {}


TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")


def _codex_turn_usage(run: AgentRun) -> list[dict]:
    if run.runtime != "codex":
        return []
    turns = []
    for line in run.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            turns.append(event["usage"])
    return turns


def agent_usage(run: AgentRun) -> dict[str, float | int]:
    """Cost, turns and tokens. Claude reports its own cost; Codex reports tokens per turn and no price."""
    report = _claude_report(run)
    usage: dict[str, float | int] = {key: report[key] for key in ("total_cost_usd", "num_turns") if key in report}
    claude_tokens = report.get("usage") or {}
    usage.update({key: claude_tokens[key] for key in TOKEN_KEYS if key in claude_tokens})
    turns = _codex_turn_usage(run)
    if turns:
        usage["num_turns"] = len(turns)
        usage.update({key: sum(turn.get(key, 0) for turn in turns) for key in TOKEN_KEYS})
    return usage


def agent_failure(run: AgentRun) -> str | None:
    """Why the agent exited non-zero, so a login or network failure never reads as a bad attempt."""
    if run.exit_code == 0:
        return None
    if run.timed_out:
        return "The agent hit the case timeout."
    report = _claude_report(run)
    if report.get("is_error") and report.get("result"):
        return str(report["result"])
    stderr_lines = [line for line in run.stderr.splitlines() if line.strip()]
    return stderr_lines[-1] if stderr_lines else f"The agent exited with code {run.exit_code}."


def run_agent(runtime: Runtime, model: str, prompt: str, workdir: Path, timeout_seconds: int) -> AgentRun:
    # Read before the agent runs: a failing version probe after a completed run would otherwise
    # raise past the point where the caller collects the diff and log, discarding both.
    version = agent_version(runtime)
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            agent_command(runtime, model),
            cwd=workdir,
            env=agent_environment(os.environ, runtime),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as expired:
        timed_out = True
        exit_code, stdout, stderr = -1, _decode(expired.stdout), _decode(expired.stderr)
    return AgentRun(
        runtime=runtime,
        model=model,
        agent_version=version,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_seconds=round(time.monotonic() - started, 1),
        stdout=stdout,
        stderr=stderr,
    )


def _decode(output: str | bytes | None) -> str:
    if output is None:
        return ""
    return output.decode(errors="replace") if isinstance(output, bytes) else output
