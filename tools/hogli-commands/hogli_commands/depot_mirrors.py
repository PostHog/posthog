"""Keeps the Depot CI mirrors of the local actions in sync with their canonical copies.

`.github/workflows/ci-depot-action-mirrors.yml` runs this file with the runner's python3 before any
dependency install, and `hogli ci:preflight` imports it, so it must stay standard library only.
"""

from __future__ import annotations

import re
import sys
import subprocess
from pathlib import Path

# These mirrors carry intentional deltas that each mirror's header documents.
# Every other mirror matches its canonical action byte for byte, apart from the SHA pins below.
DELTA_MIRRORS = frozenset({"commit-snapshots", "pnpm-install", "setup-pnpm"})
# Depot CI does not read the lockfile, so a mirror pins each action that its canonical copy
# references by tag to the commit the lockfile records for that tag, and names the tag in a comment.
LOCKFILE = ".github/workflows/actions.lock"
LOCKED_COMMIT = re.compile(
    r"^    '([^']+)':\n        ref: '[^']*'\n        commit: 'sha1-([0-9a-f]{40})'", re.MULTILINE
)
SHA_PIN_HEADER = b"# Keeps third-party actions pinned to commit SHAs, because Depot CI does not read .github/workflows/actions.lock.\n"
SHA_PINNED_USE = re.compile(rb"(uses:\s*)([^\s@]+)@([0-9a-f]{40}) # (\S+)")
# Depot resolves both `./.github/actions/<name>` and `./.depot/actions/<name>` from .depot/actions/<name>.
LOCAL_ACTION_USE = re.compile(r"""uses:\s*['"]?\./\.(?:github|depot)/actions/([A-Za-z0-9_.-]+)""")


def used_mirrors(root: Path) -> set[str]:
    return {name for path in (root / ".depot").rglob("*.y*ml") for name in LOCAL_ACTION_USE.findall(path.read_text())}


def _locked_commits(root: Path) -> dict[str, str]:
    lockfile = root / LOCKFILE
    return dict(LOCKED_COMMIT.findall(lockfile.read_text())) if lockfile.is_file() else {}


def _unpinned(content: bytes, locked: dict[str, str]) -> bytes:
    def unpin(match: re.Match[bytes]) -> bytes:
        action, sha, tag = (group.decode() for group in match.group(2, 3, 4))
        # The lockfile keys an action by its repository, so `actions/cache/restore` looks up `actions/cache`.
        repository = "/".join(action.split("/")[:2])
        if locked.get(f"{repository}@{tag}") != sha:
            return match[0]
        return match[1] + f"{action}@{tag}".encode()

    return SHA_PINNED_USE.sub(unpin, content.removeprefix(SHA_PIN_HEADER))


def _file_bytes(directory: Path, locked: dict[str, str]) -> dict[Path, bytes]:
    return {
        path.relative_to(directory): _unpinned(path.read_bytes(), locked)
        for path in directory.rglob("*")
        if path.is_file()
    }


def mirror_violations(root: Path, changed: set[str]) -> list[str]:
    violations: list[str] = []
    locked = _locked_commits(root)
    for name in sorted(used_mirrors(root)):
        canonical = f".github/actions/{name}/"
        mirror = f".depot/actions/{name}/"
        if not (root / mirror).is_dir():
            violations.append(f"A Depot file uses the {name} action, but {mirror} does not exist.")
            continue
        violations.extend(
            f"{path} changed without a matching update to {mirror}{path.removeprefix(canonical)}."
            for path in sorted(changed)
            if path.startswith(canonical) and mirror + path.removeprefix(canonical) not in changed
        )
        if name not in DELTA_MIRRORS and _file_bytes(root / canonical, locked) != _file_bytes(root / mirror, locked):
            violations.append(f"{mirror} differs from its canonical copy {canonical}.")
    return violations


def main(base_sha: str) -> int:
    diff = subprocess.run(["git", "diff", "--name-only", base_sha, "HEAD"], check=True, capture_output=True, text=True)
    changed = set(diff.stdout.splitlines())
    violations = mirror_violations(Path.cwd(), changed)
    sys.stdout.writelines(f"::error::{violation}\n" for violation in violations)
    if not violations:
        sys.stdout.write("The Depot action mirrors are in sync.\n")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
