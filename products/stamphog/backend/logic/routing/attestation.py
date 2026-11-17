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


def _listed_files(client: StamphogGitHubClient, repository: str, pr: Mapping[str, Any]) -> list[dict] | None:
    """The files GitHub lists for the live pull request, or None when the list leaves a file out."""
    files = client.get_pr_files(repository, int(pr.get("number") or 0))
    changed_files = pr.get("changed_files")
    if isinstance(changed_files, int) and len(files) < changed_files:
        # A file that GitHub did not list can be one that no proof names.
        return None
    return files


def read_attestation_proof(
    client: StamphogGitHubClient, repository: str, pr: Mapping[str, Any], *, verify: bool
) -> AttestationProof:
    """The proof for the live pull request ``pr``.

    Without ``verify`` it reads no check run, so the answer only names the checks to wait for. With
    ``verify`` it reads the head's check runs and merge base, so ``proven`` means the engine verified
    every changed file.
    """
    pr_number = int(pr.get("number") or 0)
    policy_text = client.get_default_branch_file(repository, STAMPHOG_POLICY_ENTRYPOINT)
    if policy_text is None:
        # The shipped default policy declares no attestations, so without the repo's own policy nothing is proven.
        return NO_PROOF
    context: dict[str, Any] = {"repo": repository, "pr": dict(pr)}
    if verify:
        head_sha = str((pr.get("head") or {}).get("sha") or "")
        base_sha = str((pr.get("base") or {}).get("sha") or "")
        merge_base_sha = client.get_merge_base_sha(repository, base_sha, head_sha)
        # The files API answers for whatever head is live, and a push can land after `pr` was read. The proof
        # names one head, so the list is pinned to that head's commits.
        files = client.compare_files(repository, merge_base_sha, head_sha)
        if files is None:
            return NO_PROOF
        context["check_runs"] = get_check_runs_with_pins(client, repository, head_sha)
        context["merge_base_sha"] = merge_base_sha
    else:
        files = _listed_files(client, repository, pr)
        if files is None:
            return NO_PROOF
    context["files"] = files
    try:
        return run_engine_attestation_proof(context, {STAMPHOG_POLICY_ENTRYPOINT: policy_text})
    except EnginePregateError:
        logger.warning("stamphog_reviewer_routing_attestation_proof_failed", repo=repository, pr_number=pr_number)
        return NO_PROOF
