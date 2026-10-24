import os
import json
import time
import signal
import tempfile
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


def agent_usage(run: AgentRun) -> dict[str, float | int]:
    """Cost and turn count as the Claude CLI reports them; Codex emits an event stream we do not parse."""
    report = _claude_report(run)
    return {key: report[key] for key in ("total_cost_usd", "num_turns") if key in report}


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


MAX_CAPTURED_OUTPUT_BYTES = 2_000_000


def _tail(path: Path) -> str:
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - MAX_CAPTURED_OUTPUT_BYTES))
        return handle.read().decode(errors="replace")


def run_agent(runtime: Runtime, model: str, prompt: str, workdir: Path, timeout_seconds: int) -> AgentRun:
    # Read before the agent runs: a failing version probe after a completed run would otherwise
    # raise past the point where the caller collects the diff and log, discarding both.
    version = agent_version(runtime)
    started = time.monotonic()
    timed_out = False
    # Output goes to files outside the checkout, so a verbose run cannot exhaust memory and only its tail is kept.
    with tempfile.TemporaryDirectory(prefix="golden-agent-out-") as out_dir:
        stdout_path, stderr_path = Path(out_dir, "stdout"), Path(out_dir, "stderr")
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            # Its own process group, so a timeout can stop the shell commands the agent started too.
            process = subprocess.Popen(
                agent_command(runtime, model),
                cwd=workdir,
                env=agent_environment(os.environ, runtime),
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                start_new_session=True,
            )
            try:
                process.communicate(input=prompt, timeout=timeout_seconds)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = -1
            finally:
                _kill_process_group(process)
        stdout, stderr = _tail(stdout_path), _tail(stderr_path)
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


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()
