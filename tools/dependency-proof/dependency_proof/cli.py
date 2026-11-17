"""The commands the Dependency proof and Dependency scan workflows run.

This is the only module that reads the environment. Each command turns it into one typed value
and passes that down.
"""

from __future__ import annotations

import re
import sys
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dependency_proof import prove, scan
from dependency_proof.core import identity
from dependency_proof.core.policy import Refused


@dataclass(frozen=True)
class StepFiles:
    """The files the runner reads a step's outputs and summary from."""

    output: Path
    summary: Path


def identify_request(env: Mapping[str, str]) -> prove.IdentifyRequest:
    return prove.IdentifyRequest(repository=env["REPOSITORY"], base_branch=env["BASE_BRANCH"], head_sha=env["HEAD_SHA"])


def prove_request(env: Mapping[str, str]) -> prove.ProveRequest:
    """The prove job's request, refused unless the identification job handed over well-formed values."""
    merge_base = env["MERGE_BASE"]
    identity.check_handover(env["PULL_REQUEST"], merge_base)
    return prove.ProveRequest(
        head_sha=env["HEAD_SHA"],
        workflow_sha=env["WORKFLOW_SHA"],
        merge_base=merge_base,
        merge_base_dir=Path(env["MERGE_BASE_DIR"]),
    )


def scan_report_request(env: Mapping[str, str]) -> scan.ReportRequest:
    return scan.ReportRequest(
        base=env.get("BASE_REF", "HEAD^1"),
        head=env.get("HEAD_REF", "HEAD"),
        findings_path=env.get("FINDINGS_FILE"),
        sarif_path=env.get("SARIF_FILE"),
        summary_path=env.get("GITHUB_STEP_SUMMARY"),
    )


def scan_gate_request(env: Mapping[str, str]) -> scan.GateRequest:
    return scan.GateRequest(
        base=env["MERGE_BASE"],
        head=env["HEAD_SHA"],
        output_path=env["GITHUB_OUTPUT"],
        summary_path=env.get("GITHUB_STEP_SUMMARY"),
    )


def printable(text: str) -> str:
    return re.sub(r"[^\x20-\x7e]", "?", text)


def log(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def run_prover(command: str, env: Mapping[str, str]) -> int:
    """Runs `identify` or `prove`, and writes the answer, a refusal included, to the step outputs."""
    step_files = StepFiles(output=Path(env["GITHUB_OUTPUT"]), summary=Path(env["GITHUB_STEP_SUMMARY"]))
    outputs = (
        {"pr": "0", "merge_base": "", "eligible": "false"} if command == "identify" else {"files": "[]", "blobs": "{}"}
    )
    # Package names and paths from the pull request reach the log, in pnpm's output and in a refusal,
    # so the runner must not read commands from it.
    token = secrets.token_hex(16)
    log(f"::stop-commands::{token}")
    try:
        if command == "identify":
            request = identify_request(env)
            found = prove.identify(request, prove.GitHub(request.repository, env["GITHUB_TOKEN"]))
            if found is None:
                summary = "No pull request at this head is eligible for a proof"
            else:
                outputs = {"pr": str(found.pr), "merge_base": found.merge_base, "eligible": "true"}
                summary = f"Pull request {found.pr} is eligible for a proof"
        else:
            proof = prove.prove(
                prove_request(env), prove.Git(Path.cwd()), prove.registry_metadata, prove.run_command, datetime.now(UTC)
            )
            outputs = {"files": json.dumps(proof.files), "blobs": json.dumps(proof.blobs)}
            summary = f"Attested {', '.join(proof.files)}"
    except Refused as refusal:
        # A refusal is an answer, so the job passes. Only a failure of the prover itself fails the run.
        summary, outputs = f"Refused: {refusal}", {**outputs, "refused": "true"}
    log(printable(summary))
    log(f"::{token}::")
    with step_files.output.open("a") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in outputs.items())
    with step_files.summary.open("a") as handle:
        handle.write(f"### Dependency proof\n\n{printable(summary)}\n")
    return 0


def main(argv: list[str], env: Mapping[str, str]) -> int:
    command = argv[0]
    if command == "scan-report":
        return scan.report(scan_report_request(env))
    if command == "scan-gate":
        return scan.gate(scan_gate_request(env))
    if command in ("identify", "prove"):
        return run_prover(command, env)
    raise SystemExit(f"unknown command: {command}")
