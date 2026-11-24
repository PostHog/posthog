"""Find the issuer manifests that a repository's policy names.

An attestation entry in `.stamphog/policy.yml` may name its publisher's own manifest under
`issuer`. The engine reads that manifest beside the policy and has no network, so the server reads
each named manifest from the default branch like the policy files, and puts it into the review tree
after it removes the PR head's copy.
"""

import re
from pathlib import PurePosixPath
from typing import TypeGuard

import yaml

from products.stamphog.backend.temporal.constants import (
    STAMPHOG_SANDBOX_ENGINE_DIR,
    STAMPHOG_SANDBOX_OWNERS_DIR,
    STAMPHOG_SANDBOX_REPO_DIR,
)

# Mirrors `is_issuer_path` in the engine's policy.py, which refuses a policy whose `issuer` breaks it.
# The worker writes the manifest into the tree it runs the engine from, at the path the repository
# chose. A `.py` file there, or any file beside the engine or owners modules, would be imported by
# the worker's engine subprocess as code. So only a YAML file outside those directories is written,
# and the engine then refuses the policy that names any other path.
# Letters, digits, `.`, `_`, `-` and `/` only. A `%` escape such as `%2e%2e` would pass the segment
# check below and still turn into `..` when a URL is decoded.
_ISSUER_PATH_RE = re.compile(r"[A-Za-z0-9._/-]+")
_MANIFEST_SUFFIXES = (".yml", ".yaml")
_ENGINE_TREE_PREFIXES = tuple(
    f"{PurePosixPath(directory).relative_to(STAMPHOG_SANDBOX_REPO_DIR).as_posix()}/"
    for directory in (STAMPHOG_SANDBOX_ENGINE_DIR, STAMPHOG_SANDBOX_OWNERS_DIR)
)


def _is_plain_file_path(path: object) -> TypeGuard[str]:
    if not isinstance(path, str) or not _ISSUER_PATH_RE.fullmatch(path) or not path.endswith(_MANIFEST_SUFFIXES):
        return False
    if path.startswith(_ENGINE_TREE_PREFIXES):
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/"))


def issuer_manifest_paths(policy_text: str | None) -> tuple[str, ...]:
    """The `issuer` path of each attestation entry in the repository's policy.yml, sorted and unique.

    The shipped default policy declares no attestations, so the repository's `attestations` and
    `extend_attestations` lists hold every entry the merged policy can have.
    """
    if not policy_text:
        return ()
    try:
        parsed = yaml.safe_load(policy_text)
    except yaml.YAMLError:
        return ()
    if not isinstance(parsed, dict):
        return ()
    paths: set[str] = set()
    for key in ("attestations", "extend_attestations"):
        entries = parsed.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            issuer = entry.get("issuer") if isinstance(entry, dict) else None
            if _is_plain_file_path(issuer):
                paths.add(issuer)
    return tuple(sorted(paths))
