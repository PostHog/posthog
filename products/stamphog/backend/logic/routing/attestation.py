"""What the repo policy's attestations prove about a pull request, as reviewer routing reads it.

The engine decides it with its own verifier, in the same worker tree as the pre-check, so routing
and the review agree on what a proof covers. Any failure answers no proof, which routes in full.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog

from products.stamphog.backend.logic.attestation_checks import AttestationCheck
from products.stamphog.backend.logic.engine_pregate import (
    AttestationProof,
    EnginePregateError,
    run_engine_attestation_proof,
)
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.issuer_manifests import issuer_manifest_paths
from products.stamphog.backend.logic.routing.candidates import files_truncated
from products.stamphog.backend.logic.workflow_proofs import proven_check_runs
from products.stamphog.backend.temporal.constants import STAMPHOG_POLICY_ENTRYPOINT

logger = structlog.get_logger(__name__)

NO_PROOF = AttestationProof(checks=(), proven=False)


def _listed_files(client: StamphogGitHubClient, repository: str, pr: Mapping[str, Any]) -> list[dict] | None:
    """The files GitHub lists for the live pull request, or None when the list leaves a file out."""
    files = client.get_pr_files(repository, int(pr.get("number") or 0))
    if files_truncated(pr, len(files)):
        return None
    return files


def _policy_files(client: StamphogGitHubClient, repository: str) -> dict[str, str] | None:
    """The default branch's policy.yml and the issuer manifests it names, or None without a policy.yml.

    The shipped default policy declares no attestations, so without the repo's own policy nothing is proven.
    An absent manifest is left out, which leaves its entry unusable. A manifest is read as the blob at
    its path, the way the review reads it, so a symlinked manifest leaves its entry unusable too.
    """
    policy_text = client.get_default_branch_file(repository, STAMPHOG_POLICY_ENTRYPOINT)
    if policy_text is None:
        return None
    policy_files = {STAMPHOG_POLICY_ENTRYPOINT: policy_text}
    for path in issuer_manifest_paths(policy_text):
        content = client.get_default_branch_blob_text(repository, path)
        if content is not None:
            policy_files[path] = content
    return policy_files


def _run_proof(
    repository: str, pr: Mapping[str, Any], policy_files: dict[str, str], context: dict[str, Any]
) -> AttestationProof:
    try:
        return run_engine_attestation_proof(context, policy_files)
    except EnginePregateError:
        logger.warning(
            "stamphog_reviewer_routing_attestation_proof_failed", repo=repository, pr_number=int(pr.get("number") or 0)
        )
        return NO_PROOF


def attestation_checks_to_wait_for(
    client: StamphogGitHubClient, repository: str, pr: Mapping[str, Any]
) -> tuple[AttestationCheck, ...]:
    """The checks of the attestations that cover every changed file of the live pull request ``pr``.

    It reads no check run, so the engine only names the checks and proves nothing.
    """
    policy_files = _policy_files(client, repository)
    if policy_files is None:
        return ()
    files = _listed_files(client, repository, pr)
    if files is None:
        return ()
    context: dict[str, Any] = {"repo": repository, "pr": dict(pr), "files": files}
    return _run_proof(repository, pr, policy_files, context).checks


def attestation_proven(client: StamphogGitHubClient, repository: str, pr: Mapping[str, Any]) -> bool:
    """Whether the engine verified that the attestations of the live pull request ``pr`` cover every changed file."""
    policy_files = _policy_files(client, repository)
    if policy_files is None:
        return False
    head_sha = str((pr.get("head") or {}).get("sha") or "")
    base_sha = str((pr.get("base") or {}).get("sha") or "")
    merge_base_sha = client.get_merge_base_sha(repository, base_sha, head_sha)
    # The files API answers for whatever head is live, and a push can land after `pr` was read. The proof
    # names one head, so the list is pinned to that head's commits.
    files = client.compare_files(repository, merge_base_sha, head_sha)
    if files is None:
        return False
    context: dict[str, Any] = {
        "repo": repository,
        "pr": dict(pr),
        "check_runs": proven_check_runs(
            client,
            repository,
            pr_number=int(pr.get("number") or 0),
            head_sha=head_sha,
            check_runs=client.get_check_runs(repository, head_sha),
            policy=policy_files[STAMPHOG_POLICY_ENTRYPOINT],
        ),
        "merge_base_sha": merge_base_sha,
        "files": files,
    }
    return _run_proof(repository, pr, policy_files, context).proven
