"""The repository's default-branch policy files that go into the engine's tree.

The sandbox review, the worker's gate pre-check and its gate attestation all write the same trusted
set, so every run judges a PR under the same policy.
"""

from __future__ import annotations

import yaml
import structlog

from products.stamphog.backend.logic.issuer_manifests import issuer_manifest_paths
from products.stamphog.backend.temporal.constants import (
    STAMPHOG_OPTIONAL_POLICY_PATHS,
    STAMPHOG_POLICY_ENTRYPOINT,
    STAMPHOG_POLICY_PATHS,
)

logger = structlog.get_logger(__name__)


def checked_repo_policy_yaml(repo: str, repo_text: str) -> str:
    """The repository's policy.yml as it is, once it parses as a YAML mapping.

    The engine merges it onto the default it ships (`merge_policy` in the engine's policy.py) and
    validates the result. This check only fails a malformed file closed before a sandbox exists:
    the repository declared something, and reviewing under pure defaults would be wrong.
    """
    try:
        overlay = yaml.safe_load(repo_text)
    except yaml.YAMLError as exc:
        # PyYAML puts the bad tag on the first line, and run.error keeps that line. Anyone with
        # code_review_approval:read can read it without access to the repository, so log the parser text instead.
        logger.exception("stamphog_policy_yaml_malformed", repo=repo)
        raise RuntimeError(f"repo {repo} has malformed YAML in .stamphog/policy.yml") from exc
    if not isinstance(overlay, dict):
        raise RuntimeError(f"repo {repo} .stamphog/policy.yml must be a YAML mapping to overlay the defaults")
    return repo_text


def effective_policy_files(repo: str, policy_files: dict[str, str]) -> dict[str, str]:
    """The repository's default-branch policy files that go into the tree, as they are.

    The engine ships the defaults and layers these over them: it merges policy.yml onto its default
    policy, a review-guidance.md replaces its default guidance, and steering.md is appended. A file
    the repository does not carry is left out, and the PR head's copy is still wiped.
    """
    defaulted = [path for path in STAMPHOG_POLICY_PATHS if path not in policy_files]
    if defaulted:
        logger.info("stamphog_policy_files_defaulted", repo=repo, defaulted=defaulted)

    effective = {
        path: policy_files[path]
        for path in (*STAMPHOG_POLICY_PATHS, *STAMPHOG_OPTIONAL_POLICY_PATHS)
        if path in policy_files
    }
    if STAMPHOG_POLICY_ENTRYPOINT in effective:
        effective[STAMPHOG_POLICY_ENTRYPOINT] = checked_repo_policy_yaml(repo, effective[STAMPHOG_POLICY_ENTRYPOINT])
    for path in issuer_manifest_paths(effective.get(STAMPHOG_POLICY_ENTRYPOINT)):
        if path in policy_files:
            effective[path] = policy_files[path]
    return effective
