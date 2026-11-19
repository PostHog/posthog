"""The commands the Dependency proof, Dependency scan and Revert proof workflows run.

This is the only module that reads the environment. Each command turns it into one typed value
and passes that down.
"""

from __future__ import annotations

import re
import sys
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from change_prover import prove, prove_revert, scan
from change_prover.core import conclusion, identity
from change_prover.core.policy import Refused

NOT_IDENTIFIED = {"pr": "0", "merge_base": "", "eligible": "false"}
NOT_REVERT_IDENTIFIED = {**NOT_IDENTIFIED, "reverted": ""}
NOT_PROVED = {"files": "[]", "blobs": "{}"}
# A step's summary line and its outputs.
StepAnswer = tuple[str, dict[str, str]]


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


def revert_prove_request(env: Mapping[str, str]) -> prove_revert.RevertProveRequest:
    """The revert prove job's request, refused unless the identification job handed over well-formed values."""
    merge_base, reverted = env["MERGE_BASE"], env["REVERTED"]
    identity.check_handover(env["PULL_REQUEST"], merge_base)
    identity.check_reverted_handover(reverted)
    return prove_revert.RevertProveRequest(
        head_sha=env["HEAD_SHA"], workflow_sha=env["WORKFLOW_SHA"], merge_base=merge_base, reverted=reverted
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


def publish_inputs(env: Mapping[str, str], *, scanned: bool) -> conclusion.PublishInputs:
    """The other jobs' results from the environment. A lane with a scan job must pass its results too."""
    return conclusion.PublishInputs(
        head_sha=env["HEAD_SHA"],
        workflow_sha=env["WORKFLOW_SHA"],
        details_url=env["RUN_URL"],
        identify_result=env["IDENTIFY_RESULT"],
        identify_pr=env["IDENTIFY_PR"],
        identify_merge_base=env["IDENTIFY_MERGE_BASE"],
        identify_eligible=env["IDENTIFY_ELIGIBLE"],
        identify_refused=env["IDENTIFY_REFUSED"],
        prove_result=env["PROVE_RESULT"],
        prove_files=env["PROVE_FILES"],
        prove_blobs=env["PROVE_BLOBS"],
        prove_refused=env["PROVE_REFUSED"],
        scan_result=env["SCAN_RESULT"] if scanned else None,
        scan_clean=env["SCAN_CLEAN"] if scanned else None,
    )


def run_conclude(inputs: conclusion.PublishInputs, lane: conclusion.Lane) -> int:
    """Prints the lane's check run to post, and exits 1 when the change went unproved."""
    decided = conclusion.conclude(inputs, lane)
    sys.stdout.write(json.dumps(decided.check_run) + "\n")
    return 1 if decided.unproved else 0


def printable(text: str) -> str:
    return re.sub(r"[^\x20-\x7e]", "?", text)


def log(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def run_step(heading: str, refused: dict[str, str], work: Callable[[], StepAnswer], env: Mapping[str, str]) -> int:
    """Runs one identify or prove step, and writes its answer, a refusal included, to the step outputs.

    `refused` holds the outputs the step writes when it refuses.
    """
    step_files = StepFiles(output=Path(env["GITHUB_OUTPUT"]), summary=Path(env["GITHUB_STEP_SUMMARY"]))
    # Package names, paths and commit messages from the pull request reach the log, in a tool's
    # output and in a refusal, so the runner must not read commands from it.
    token = secrets.token_hex(16)
    log(f"::stop-commands::{token}")
    try:
        summary, outputs = work()
    except Refused as refusal:
        # A refusal is an answer, so the job passes. Only a failure of the prover itself fails the run.
        summary, outputs = f"Refused: {refusal}", {**refused, "refused": "true"}
    log(printable(summary))
    log(f"::{token}::")
    with step_files.output.open("a") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in outputs.items())
    with step_files.summary.open("a") as handle:
        handle.write(f"### {heading}\n\n{printable(summary)}\n")
    return 0


def identify_dependency(env: Mapping[str, str]) -> StepAnswer:
    request = identify_request(env)
    found = prove.identify(request, prove.GitHub(request.repository, env["GITHUB_TOKEN"]))
    if found is None:
        return "No pull request at this head is eligible for a proof", NOT_IDENTIFIED
    outputs = {"pr": str(found.pr), "merge_base": found.merge_base, "eligible": "true"}
    return f"Pull request {found.pr} is eligible for a proof", outputs


def prove_dependency(env: Mapping[str, str]) -> StepAnswer:
    proof = prove.prove(
        prove_request(env), prove.Git(Path.cwd()), prove.registry_metadata, prove.run_command, datetime.now(UTC)
    )
    return f"Attested {', '.join(proof.files)}", {"files": json.dumps(proof.files), "blobs": json.dumps(proof.blobs)}


def identify_revert(env: Mapping[str, str]) -> StepAnswer:
    request = identify_request(env)
    github = prove.GitHub(request.repository, env["GITHUB_TOKEN"])
    found = prove_revert.identify(request, github, datetime.now(UTC))
    if found is None:
        return "No open pull request has this head", NOT_REVERT_IDENTIFIED
    if found.reverted is None:
        outputs = {"pr": str(found.pr), "merge_base": found.merge_base, "eligible": "false", "reverted": ""}
        return f"Pull request {found.pr} reverts no commit", outputs
    outputs = {"pr": str(found.pr), "merge_base": found.merge_base, "eligible": "true", "reverted": found.reverted}
    return f"Pull request {found.pr} reverts {found.reverted}", outputs


def prove_reverted(env: Mapping[str, str]) -> StepAnswer:
    proof = prove_revert.prove(revert_prove_request(env), prove.Git(Path.cwd()))
    return f"Attested {', '.join(proof.files)}", {"files": json.dumps(proof.files), "blobs": json.dumps(proof.blobs)}


def main(argv: list[str], env: Mapping[str, str]) -> int:
    command = argv[0]
    if command == "scan-report":
        return scan.report(scan_report_request(env))
    if command == "scan-gate":
        return scan.gate(scan_gate_request(env))
    if command == "identify":
        return run_step("Dependency proof", NOT_IDENTIFIED, lambda: identify_dependency(env), env)
    if command == "prove":
        return run_step("Dependency proof", NOT_PROVED, lambda: prove_dependency(env), env)
    if command == "conclude":
        return run_conclude(publish_inputs(env, scanned=True), conclusion.DEPENDENCY)
    if command == "revert-identify":
        return run_step("Revert proof", NOT_REVERT_IDENTIFIED, lambda: identify_revert(env), env)
    if command == "revert-prove":
        return run_step("Revert proof", NOT_PROVED, lambda: prove_reverted(env), env)
    if command == "revert-conclude":
        return run_conclude(publish_inputs(env, scanned=False), conclusion.REVERT)
    raise SystemExit(f"unknown command: {command}")
