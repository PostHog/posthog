"""Find the issuer manifests that a repository's policy names.

An attestation entry in `.stamphog/policy.yml` may name its publisher's own manifest under
`issuer`. The engine reads that manifest beside the policy and has no network, so the server reads
each named manifest from the default branch like the policy files, and puts it into the review tree
after it removes the PR head's copy.
"""

import re
from typing import TypeGuard

import yaml

# Mirrors `is_plain_repo_path` in the engine's policy.py, which refuses a policy whose `issuer` breaks
# it. The server writes the manifest into a tree at this path, so a path that escapes the tree or
# names a directory is never written, and the engine then refuses the policy that names it.
_GLOB_CHARACTERS_RE = re.compile(r"[*?\[\]{}\\]")


def _is_plain_file_path(path: object) -> TypeGuard[str]:
    if not isinstance(path, str) or not path or path.endswith("/") or _GLOB_CHARACTERS_RE.search(path):
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
