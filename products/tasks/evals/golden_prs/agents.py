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


def agent_environment(env: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in env.items() if key not in GITHUB_CREDENTIAL_VARS}


def agent_version(runtime: Runtime) -> str:
    return subprocess.run([runtime, "--version"], capture_output=True, text=True, check=True).stdout.strip()


def agent_usage(run: AgentRun) -> dict[str, float | int]:
    """Cost and turn count as the Claude CLI reports them; Codex emits an event stream we do not parse."""
    if run.runtime != "claude":
        return {}
    try:
        report = json.loads(run.stdout)
    except json.JSONDecodeError:
        return {}
    return {key: report[key] for key in ("total_cost_usd", "num_turns") if key in report}


def run_agent(runtime: Runtime, model: str, prompt: str, workdir: Path, timeout_seconds: int) -> AgentRun:
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            agent_command(runtime, model),
            cwd=workdir,
            env=agent_environment(os.environ),
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
        agent_version=agent_version(runtime),
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
