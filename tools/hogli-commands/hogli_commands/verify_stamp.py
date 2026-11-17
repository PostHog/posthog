from __future__ import annotations

import os
import re
import sys
import json
import shutil
import hashlib
import tempfile
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import click
from hogli import telemetry
from hogli.manifest import REPO_ROOT

from hogli_commands.telemetry_props import invocation_identity_properties

STAMP_FILE_NAME = "hogli-verify-stamp.json"
GATE_MODE_ENV_VAR = "HOGLI_VERIFY_GATE"
GATE_BLOCK_EXIT_CODE = 3
GATE_EVENT = "verify_gate_checked"
GATE_TELEMETRY_WAIT_SECONDS = 0.5
ESCAPE_TRAILER = re.compile(r"^Unverified:[ \t]*(\S.*)$", re.IGNORECASE | re.MULTILINE)
NO_LAYER = "none"
FAILED_OUTCOME = "failed"


class GateMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    ENFORCE = "enforce"


class GateVerdict(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    STALE = "stale"
    MISSING = "missing"
    ESCAPED = "escaped"
    ERROR = "error"


@dataclass(frozen=True, kw_only=True, slots=True)
class VerifyStamp:
    content_hash: str
    head: str
    recorded_at: str
    outcome: str
    highest_layer: str
    sufficient_layer: str
    layers: dict[str, str]
    checks: dict[str, str] = field(default_factory=dict)


def _git(*args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, env=env, check=True)
    return result.stdout.strip()


def _git_path(name: str) -> Path:
    return (REPO_ROOT / _git("rev-parse", "--git-path", name)).resolve()


def stamp_path() -> Path:
    return _git_path(STAMP_FILE_NAME)


def staged_content_hash(env: dict[str, str] | None = None) -> str:
    return hashlib.sha256(_git("ls-files", "--stage", "-z", env=env).encode()).hexdigest()


def working_tree_content_hash() -> str:
    with tempfile.TemporaryDirectory() as scratch:
        scratch_index = Path(scratch) / "index"
        shutil.copyfile(_git_path("index"), scratch_index)
        env = {**os.environ, "GIT_INDEX_FILE": str(scratch_index)}
        _git("add", "--all", env=env)
        return staged_content_hash(env)


def write_stamp(
    *,
    outcome: str,
    highest_layer: str,
    sufficient_layer: str,
    layers: dict[str, str],
    checks: dict[str, str],
) -> VerifyStamp | None:
    try:
        stamp = VerifyStamp(
            content_hash=working_tree_content_hash(),
            head=_git("rev-parse", "HEAD"),
            recorded_at=datetime.now(UTC).isoformat(),
            outcome=outcome,
            highest_layer=highest_layer,
            sufficient_layer=sufficient_layer,
            layers=layers,
            checks=checks,
        )
        stamp_path().write_text(json.dumps(asdict(stamp), indent=2) + "\n")
    except Exception as error:
        click.secho(f"  Could not record the verification stamp: {error}", fg="yellow")
        return None
    telemetry.add_command_properties(
        verify_outcome=outcome,
        verify_highest_layer=highest_layer,
        verify_sufficient_layer=sufficient_layer,
        verify_layers=layers,
    )
    return stamp


def read_stamp() -> VerifyStamp | None:
    path = stamp_path()
    if not path.exists():
        return None
    return VerifyStamp(**json.loads(path.read_text()))


def gate_mode() -> GateMode:
    try:
        return GateMode(os.environ.get(GATE_MODE_ENV_VAR, GateMode.OBSERVE).strip().lower())
    except ValueError:
        return GateMode.OBSERVE


def escape_reason(commit_message: str) -> str | None:
    message_without_comments = "\n".join(line for line in commit_message.splitlines() if not line.startswith("#"))
    match = ESCAPE_TRAILER.search(message_without_comments)
    return match.group(1).strip() if match else None


def judge(stamp: VerifyStamp | None, staged_content: str, commit_message: str) -> GateVerdict:
    if stamp is None:
        unverified = GateVerdict.MISSING
    elif stamp.content_hash != staged_content:
        unverified = GateVerdict.STALE
    elif stamp.outcome == FAILED_OUTCOME or stamp.highest_layer == NO_LAYER:
        unverified = GateVerdict.FAILED
    else:
        return GateVerdict.VERIFIED
    return GateVerdict.ESCAPED if escape_reason(commit_message) else unverified


VERDICT_EXPLANATIONS: dict[GateVerdict, str] = {
    GateVerdict.MISSING: "no `hogli verify --changed` run is recorded for this checkout",
    GateVerdict.STALE: "the content changed after the last `hogli verify --changed` run",
    GateVerdict.FAILED: "the last `hogli verify --changed` run on this content failed",
}

PASSING_VERDICTS = frozenset({GateVerdict.VERIFIED, GateVerdict.ESCAPED})


def _track_gate_check(mode: GateMode, verdict: GateVerdict, would_block: bool, stamp: VerifyStamp | None) -> None:
    try:
        telemetry.track(
            GATE_EVENT,
            {
                **invocation_identity_properties(),
                "verify_gate_mode": str(mode),
                "verify_gate_verdict": str(verdict),
                "verify_gate_would_block": would_block,
                "verify_highest_layer": stamp.highest_layer if stamp else NO_LAYER,
                "verify_outcome": stamp.outcome if stamp else None,
            },
        )
        telemetry.flush(timeout=GATE_TELEMETRY_WAIT_SECONDS)
    except Exception:
        pass


@click.command(
    name="verify:gate",
    help="Check that a commit matches the last `hogli verify --changed` run (used by the commit-msg hook)",
)
@click.argument("commit_message_file", type=click.Path(path_type=Path))
def verify_gate(commit_message_file: Path) -> None:
    mode = gate_mode()
    if mode == GateMode.OFF:
        return
    stamp: VerifyStamp | None = None
    try:
        stamp = read_stamp()
        verdict = judge(stamp, staged_content_hash(), commit_message_file.read_text())
    except Exception:
        verdict = GateVerdict.ERROR
    would_block = verdict not in PASSING_VERDICTS and verdict != GateVerdict.ERROR
    _track_gate_check(mode, verdict, would_block, stamp)
    if verdict == GateVerdict.VERIFIED and stamp is not None:
        click.secho(f"hogli verify gate: verified, highest layer {stamp.highest_layer}.", dim=True, err=True)
        return
    if not would_block:
        return
    explanation = VERDICT_EXPLANATIONS[verdict]
    advice = "Run `hogli verify --changed`, or add an `Unverified: <reason>` line to the commit message."
    if mode == GateMode.OBSERVE:
        click.secho(f"hogli verify gate: would block ({verdict}): {explanation}. {advice}", fg="yellow", err=True)
        return
    click.secho(f"hogli verify gate: blocked ({verdict}): {explanation}. {advice}", fg="red", err=True)
    sys.exit(GATE_BLOCK_EXIT_CODE)
