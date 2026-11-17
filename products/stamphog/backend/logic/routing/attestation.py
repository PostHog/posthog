"""What the repo policy's attestations prove about a pull request, as reviewer routing reads it.

The engine decides it with its own verifier, in the same worker tree as the pre-check, so routing
and the review agree on what a proof covers. Any failure answers no proof, which routes in full.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog

from products.stamphog.backend.logic.attestation_pins import get_check_runs_with_pins
from products.stamphog.backend.logic.engine_pregate import (
    AttestationProof,
    EnginePregateError,
    run_engine_attestation_proof,
)
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.temporal.constants import STAMPHOG_POLICY_ENTRYPOINT

logger = structlog.get_logger(__name__)

NO_PROOF = AttestationProof(checks=(), proven=False)


def read_attestation_proof(
    client: StamphogGitHubClient, repository: str, pr: Mapping[str, Any], *, verify: bool
) -> AttestationProof:
    """The proof for the live pull request ``pr``.

    Without ``verify`` it reads no check run, so the answer only names the checks to wait for. With
    ``verify`` it reads the head's check runs and merge base, so ``proven`` means the engine verified
    every changed file.
    """
    pr_number = int(pr.get("number") or 0)
    files = client.get_pr_files(repository, pr_number)
    changed_files = pr.get("changed_files")
    if isinstance(changed_files, int) and len(files) < changed_files:
        # A file that GitHub did not list can be one that no proof names.
        return NO_PROOF
    policy_text = client.get_default_branch_file(repository, STAMPHOG_POLICY_ENTRYPOINT)
    policy_files = {} if policy_text is None else {STAMPHOG_POLICY_ENTRYPOINT: policy_text}
    context: dict[str, Any] = {"repo": repository, "pr": dict(pr), "files": files}
    if verify:
        head_sha = str((pr.get("head") or {}).get("sha") or "")
        base_sha = str((pr.get("base") or {}).get("sha") or "")
        context["check_runs"] = get_check_runs_with_pins(client, repository, head_sha)
        context["merge_base_sha"] = client.get_merge_base_sha(repository, base_sha, head_sha)
    try:
        return run_engine_attestation_proof(context, policy_files)
    except EnginePregateError:
        logger.warning("stamphog_reviewer_routing_attestation_proof_failed", repo=repository, pr_number=pr_number)
        return NO_PROOF
