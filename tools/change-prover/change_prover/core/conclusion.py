"""A lane's check run, decided from the results and outputs of the jobs before it.

stamphog reads the check name, the conclusion and the `stamphog:v1` marker in the summary, so
their shapes must not change.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import Any

BLOB_SHA = re.compile(r"[0-9a-f]{40}")
PULL_REQUEST_NUMBER = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class Lane:
    """One kind of claim: the check run it posts, and the words its titles use."""

    check_name: str
    subject: str
    attested_files: str


DEPENDENCY = Lane("Dependency proof", "dependency update", "dependency file(s)")
REVERT = Lane("Revert proof", "revert", "reverted file(s)")


@dataclass(frozen=True, kw_only=True)
class PublishInputs:
    """The `needs` results and outputs of the identify, prove and scan jobs, as the runner gives them.

    A lane without a scan job leaves `scan_result` and `scan_clean` as None.
    """

    head_sha: str
    workflow_sha: str
    details_url: str
    identify_result: str
    identify_pr: str
    identify_merge_base: str
    identify_eligible: str
    identify_refused: str
    prove_result: str
    prove_files: str
    prove_blobs: str
    prove_refused: str
    scan_result: str | None = None
    scan_clean: str | None = None


@dataclass(frozen=True)
class Conclusion:
    check_run: dict[str, Any]
    unproved: bool


def proved_files(text: str) -> list[str] | None:
    """The prove job's `files` output, or None unless it is a non-empty JSON list of strings."""
    try:
        files = json.loads(text)
    except ValueError:
        return None
    if not isinstance(files, list) or not files or not all(isinstance(path, str) for path in files):
        return None
    return files


def proved_blobs(text: str) -> dict[str, str | None] | None:
    """The prove job's `blobs` output, or None unless every value is null or a blob id."""
    try:
        blobs = json.loads(text)
    except ValueError:
        return None
    if not isinstance(blobs, dict):
        return None
    if not all(sha is None or (isinstance(sha, str) and BLOB_SHA.fullmatch(sha)) for sha in blobs.values()):
        return None
    return blobs


def conclude(inputs: PublishInputs, lane: Lane) -> Conclusion:
    """The lane's check run to post, and whether the change went unproved.

    A head with no eligible pull request gets a success that attests nothing. A refused change
    gets a neutral check, and the run passes because a refusal is an answer. A job that fails gets
    a neutral check too, and the run fails, so only a broken prover shows up red in the Actions tab.
    An unproved change fails the run the same way, and the workflow fails it for a failed job.
    """
    conclusion, files, blobs, unproved = "neutral", [], {}, False
    if inputs.identify_refused == "true" or inputs.prove_refused == "true":
        title = f"The {lane.subject} was refused"
    elif inputs.scan_result == "success" and inputs.scan_clean != "true":
        title = "The dependency scan flagged an added package"
    elif inputs.identify_result == "success" and inputs.identify_eligible == "false":
        conclusion, title = "success", "Nothing to attest"
    elif (
        inputs.identify_result == "success"
        and inputs.prove_result == "success"
        and inputs.scan_result in ("success", None)
        and (attested_files := proved_files(inputs.prove_files)) is not None
        and (attested_blobs := proved_blobs(inputs.prove_blobs)) is not None
    ):
        conclusion, files, blobs = "success", attested_files, attested_blobs
        title = f"Attested {len(files)} {lane.attested_files}"
    else:
        unproved, title = True, f"The {lane.subject} could not be proved"

    pr = int(inputs.identify_pr) if PULL_REQUEST_NUMBER.fullmatch(inputs.identify_pr) else 0
    merge_base = inputs.identify_merge_base if BLOB_SHA.fullmatch(inputs.identify_merge_base) else ""
    marker = {
        "files": files,
        "blobs": blobs,
        "pr": pr,
        "head_sha": inputs.head_sha,
        "merge_base": merge_base,
        "workflow_sha": inputs.workflow_sha,
    }
    check_run = {
        "name": lane.check_name,
        "head_sha": inputs.head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "details_url": inputs.details_url,
        "output": {
            "title": title,
            "summary": f"<!-- stamphog:v1 {json.dumps(marker, separators=(',', ':'), ensure_ascii=False)} -->",
        },
    }
    return Conclusion(check_run, unproved)
