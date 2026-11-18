from __future__ import annotations

import os
import re
import sys
import json
import shutil
import hashlib
import tempfile
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
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
ESCAPE_REASON_WORD = re.compile(r"[a-z-]+")
NO_LAYER = "none"
FAILED_OUTCOME = "failed"
VERIFIED_OUTCOME = "verified"


class GateMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    ENFORCE = "enforce"


class GateVerdict(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNVERIFIED = "unverified"
    STALE = "stale"
    MISSING = "missing"
    ESCAPED = "escaped"
    ERROR = "error"


class EscapeReason(StrEnum):
    DOCS = "docs"
    GENERATED = "generated"
    CONFIG = "config"
    TRIVIAL = "trivial"
    WIP = "wip"
    TOOLING = "tooling"
    UNTESTABLE = "untestable"
    OTHER = "other"


@dataclass(frozen=True, kw_only=True, slots=True)
class ContentSnapshot:
    content_hash: str
    head: str
    blobs_changed_from_head: dict[str, str]


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
    blobs_changed_from_head: dict[str, str] = field(default_factory=dict)


def _git_bytes(*args: str, env: dict[str, str] | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, env=env, check=True).stdout


def _git(*args: str, env: dict[str, str] | None = None) -> str:
    return _git_bytes(*args, env=env).decode().strip()


def _git_path(name: str) -> Path:
    return (REPO_ROOT / _git("rev-parse", "--git-path", name)).resolve()


def stamp_path() -> Path:
    return _git_path(STAMP_FILE_NAME)


def staged_content_hash(env: dict[str, str] | None = None) -> str:
    return hashlib.sha256(_git_bytes("ls-files", "--stage", "-z", env=env)).hexdigest()


def blobs_changed_from(commit: str, env: dict[str, str] | None = None) -> dict[str, str]:
    fields = _git_bytes("diff-index", "--cached", "--no-renames", "-z", commit, env=env).decode().split("\0")
    return {path: status.split()[3] for status, path in zip(fields[0::2], fields[1::2]) if path}


@contextmanager
def _scratch_index_with_working_tree() -> Iterator[dict[str, str]]:
    real_objects = _git_path("objects")
    with tempfile.TemporaryDirectory() as scratch:
        scratch_index = Path(scratch) / "index"
        scratch_objects = Path(scratch) / "objects"
        scratch_objects.mkdir()
        shutil.copy2(_git_path("index"), scratch_index)
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(scratch_index),
            "GIT_OBJECT_DIRECTORY": str(scratch_objects),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(real_objects),
        }
        _git("add", "--all", env=env)
        yield env


def working_tree_content_hash() -> str:
    with _scratch_index_with_working_tree() as env:
        return staged_content_hash(env)


def working_tree_snapshot() -> ContentSnapshot:
    with _scratch_index_with_working_tree() as env:
        head = _git("rev-parse", "HEAD")
        return ContentSnapshot(
            content_hash=staged_content_hash(env),
            head=head,
            blobs_changed_from_head=blobs_changed_from(head, env),
        )


def snapshot_working_tree() -> ContentSnapshot | None:
    try:
        return working_tree_snapshot()
    except Exception as error:
        click.secho(
            f"  Could not hash the working tree, so no verification stamp will be recorded: {error}", fg="yellow"
        )
        return None


def write_stamp(
    *,
    snapshot: ContentSnapshot | None,
    outcome: str,
    highest_layer: str,
    sufficient_layer: str,
    layers: dict[str, str],
    checks: dict[str, str],
) -> VerifyStamp | None:
    if snapshot is None:
        return None
    try:
        if working_tree_content_hash() != snapshot.content_hash:
            click.secho(
                "  Files changed while the checks ran. Run `hogli verify --changed` again before you commit.",
                fg="yellow",
            )
        stamp = VerifyStamp(
            content_hash=snapshot.content_hash,
            head=snapshot.head,
            recorded_at=datetime.now(UTC).isoformat(),
            outcome=outcome,
            highest_layer=highest_layer,
            sufficient_layer=sufficient_layer,
            layers=layers,
            checks=checks,
            blobs_changed_from_head=snapshot.blobs_changed_from_head,
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


def escape_reason(commit_message: str) -> EscapeReason | None:
    message_without_comments = "\n".join(line for line in commit_message.splitlines() if not line.startswith("#"))
    match = ESCAPE_TRAILER.search(message_without_comments)
    if not match:
        return None
    word = ESCAPE_REASON_WORD.match(match.group(1).lower())
    try:
        return EscapeReason(word.group(0) if word else EscapeReason.OTHER)
    except ValueError:
        return EscapeReason.OTHER


def stale_file_count(stamp: VerifyStamp) -> int:
    staged = blobs_changed_from(stamp.head)
    stamped = stamp.blobs_changed_from_head
    return sum(staged.get(path) != stamped.get(path) for path in staged.keys() | stamped.keys())


def _stamp_age_seconds(stamp: VerifyStamp) -> int | None:
    try:
        return int((datetime.now(UTC) - datetime.fromisoformat(stamp.recorded_at)).total_seconds())
    except ValueError:
        return None


def judge(stamp: VerifyStamp | None, staged_content: str, commit_message: str) -> GateVerdict:
    if stamp is None:
        unverified = GateVerdict.MISSING
    elif stamp.content_hash != staged_content:
        unverified = GateVerdict.STALE
    elif stamp.outcome == FAILED_OUTCOME or stamp.highest_layer == NO_LAYER:
        unverified = GateVerdict.FAILED
    elif stamp.outcome != VERIFIED_OUTCOME:
        unverified = GateVerdict.UNVERIFIED
    else:
        return GateVerdict.VERIFIED
    return GateVerdict.ESCAPED if escape_reason(commit_message) else unverified


VERDICT_EXPLANATIONS: dict[GateVerdict, str] = {
    GateVerdict.MISSING: "no `hogli verify --changed` run is recorded for this checkout",
    GateVerdict.STALE: "the content changed after the last `hogli verify --changed` run",
    GateVerdict.FAILED: "the last `hogli verify --changed` run on this content failed",
    GateVerdict.UNVERIFIED: "the last `hogli verify --changed` run on this content left checks outstanding",
    GateVerdict.ERROR: "the commit could not be compared with the stamp",
}

PASSING_VERDICTS = frozenset({GateVerdict.VERIFIED, GateVerdict.ESCAPED})


def _track_gate_check(
    *, mode: GateMode, verdict: GateVerdict, would_block: bool, stamp: VerifyStamp | None, escape: EscapeReason | None
) -> None:
    stale_files: int | None = None
    try:
        if stamp is not None and verdict in (GateVerdict.STALE, GateVerdict.ESCAPED):
            stale_files = stale_file_count(stamp)
    except Exception:
        pass
    try:
        telemetry.track(
            GATE_EVENT,
            {
                **invocation_identity_properties(),
                "verify_gate_mode": str(mode),
                "verify_gate_verdict": str(verdict),
                "verify_gate_would_block": would_block,
                "verify_gate_escape_reason": str(escape) if escape else None,
                "verify_stale_files": stale_files,
                "verify_stamp_age_seconds": _stamp_age_seconds(stamp) if stamp else None,
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
    commit_message = ""
    error_detail = ""
    try:
        commit_message = commit_message_file.read_text(errors="replace")
        stamp = read_stamp()
        verdict = judge(stamp, staged_content_hash(), commit_message)
    except Exception as error:
        verdict = GateVerdict.ESCAPED if escape_reason(commit_message) else GateVerdict.ERROR
        error_detail = f" ({error})"
    would_block = verdict not in PASSING_VERDICTS
    _track_gate_check(
        mode=mode, verdict=verdict, would_block=would_block, stamp=stamp, escape=escape_reason(commit_message)
    )
    if verdict == GateVerdict.VERIFIED and stamp is not None:
        click.secho(f"hogli verify gate: verified, highest layer {stamp.highest_layer}.", dim=True, err=True)
        return
    if not would_block:
        return
    explanation = VERDICT_EXPLANATIONS[verdict] + error_detail
    reasons = ", ".join(reason for reason in EscapeReason if reason != EscapeReason.OTHER)
    advice = f"Run `hogli verify --changed`, or add an `Unverified: <reason>` line to the commit message ({reasons})."
    if mode == GateMode.OBSERVE:
        click.secho(f"hogli verify gate: would block ({verdict}): {explanation}. {advice}", fg="yellow", err=True)
        return
    click.secho(f"hogli verify gate: blocked ({verdict}): {explanation}. {advice}", fg="red", err=True)
    sys.exit(GATE_BLOCK_EXIT_CODE)
