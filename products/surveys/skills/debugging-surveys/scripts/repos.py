#!/usr/bin/env python3
"""Resolve and remember local checkouts of the PostHog repos that Surveys spans.

GitHub is the source of truth for where the code lives; this script is a per-maintainer
cache of where each repo was cloned, stored at ~/.config/posthog-surveys/repos.json, so a
checkout is found once and reused instead of re-cloned every session.

Discovery is automatic: `init` (and `ensure`) scan common code roots for git checkouts and
match them by their `origin` remote (github.com/PostHog/<repo>), which handles nested
layouts without any manual setup. Git has no global registry of clone locations, so the
filesystem + origin remote is the reliable signal.

Usage:
    repos.py init                    Scan code roots, record every PostHog repo found, and
                                     print a summary. Idempotent; safe to re-run.
    repos.py get <repo>              Print the recorded path (exit 1 if unknown/missing).
    repos.py set <repo> <path>       Record an absolute path for a repo.
    repos.py list                    Print the whole registry as JSON.
    repos.py ensure <repo>           Resolve a path: registry -> filesystem scan, record
                                     the result, and print it. Add --clone to clone from
                                     GitHub when no local checkout is found.

Known repo keys: posthog, posthog-js, posthog-ios, posthog-android, posthog-flutter,
posthog.com (keys match GitHub repo names; web + React Native both live in posthog-js).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REGISTRY = Path.home() / ".config" / "posthog-surveys" / "repos.json"

KNOWN_REPOS = {
    "posthog",
    "posthog-js",
    "posthog-ios",
    "posthog-android",
    "posthog-flutter",
    "posthog.com",
}

# Roots to scan for existing checkouts, in priority order. Kept to conventional code homes
# rather than all of $HOME so the walk stays fast and avoids Library/Application noise.
def _scan_roots() -> list[Path]:
    cwd = Path.cwd()
    candidates = [
        cwd.parent,
        cwd.parent.parent,
        Path.home() / "src",
        Path.home() / "code",
        Path.home() / "dev",
        Path.home() / "projects",
        Path.home() / "repos",
        Path.home() / "work",
        Path.home() / "git",
    ]
    seen: set[Path] = set()
    roots: list[Path] = []
    for c in candidates:
        if c.is_dir() and c not in seen:
            seen.add(c)
            roots.append(c)
    return roots


# Don't descend into these — they never contain a sibling checkout and dominate walk time.
_PRUNE = {"node_modules", ".venv", "venv", "vendor", "Pods", "build", "dist", ".next", "target", ".cache"}
_MAX_DEPTH = 4

_ORIGIN_RE = re.compile(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', re.DOTALL)


def load_registry() -> dict[str, str]:
    if not REGISTRY.exists():
        return {}
    try:
        data = json.loads(REGISTRY.read_text())
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save_registry(registry: dict[str, str]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")


def record(repo: str, path: Path) -> Path:
    registry = load_registry()
    registry[repo] = str(path.resolve())
    save_registry(registry)
    return path.resolve()


def origin_url(repo_dir: Path) -> str | None:
    """Read origin remote from .git/config directly — faster than spawning git, and works
    for the common case of a top-level clone (where .git is a directory)."""
    config = repo_dir / ".git" / "config"
    if not config.is_file():
        return None
    try:
        match = _ORIGIN_RE.search(config.read_text(errors="ignore"))
    except OSError:
        return None
    return match.group(1) if match else None


def repo_key_for_origin(url: str) -> str | None:
    """Map a git origin URL to a known repo key, e.g.
    https://github.com/PostHog/posthog-js.git -> posthog-js."""
    normalized = url.lower().rstrip("/").removesuffix(".git")
    for repo in KNOWN_REPOS:
        if normalized.endswith(f"posthog/{repo.lower()}"):
            return repo
    return None


def is_repo_checkout(path: Path, repo: str) -> bool:
    """Strict: a directory is the repo only if its git origin proves it. No name-based
    fallback — a folder merely named `posthog-js` is not trusted as the real checkout."""
    return path.is_dir() and bool((url := origin_url(path))) and repo_key_for_origin(url) == repo


def discover(wanted: set[str] | None = None) -> dict[str, list[Path]]:
    """Walk the scan roots and return {repo_key: [paths]} for every PostHog repo found.
    A repo can map to more than one path when the same repo is checked out twice.
    `wanted` limits the search so `ensure` can stop as soon as it has its target(s)."""
    found: dict[str, list[Path]] = {}
    for root in _scan_roots():
        root_depth = len(root.parts)
        for dirpath, dirnames, _ in os.walk(root):
            here = Path(dirpath)
            if ".git" in dirnames or (here / ".git").is_dir():
                url = origin_url(here)
                key = repo_key_for_origin(url) if url else None
                if key:
                    resolved = here.resolve()
                    paths = found.setdefault(key, [])
                    if resolved not in paths:
                        paths.append(resolved)
                # A checkout never contains a sibling checkout we care about — stop descending.
                dirnames[:] = []
                if wanted and wanted.issubset(found.keys()):
                    return found
                continue
            # Prune noise and cap depth.
            if len(here.parts) - root_depth >= _MAX_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames if d not in _PRUNE and not d.startswith(".")]
    return found


def clone(repo: str) -> Path | None:
    dest = Path.home() / "src" / repo
    if dest.exists():
        # Only trust a preexisting path if its git origin proves it's the right repo —
        # otherwise an unrelated/leftover directory would poison the registry.
        if is_repo_checkout(dest, repo):
            return dest.resolve()
        print(f"'{dest}' exists but is not a checkout of PostHog/{repo}; not recording it.", file=sys.stderr)
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/PostHog/{repo}"
    print(f"Cloning {url} -> {dest} ...", file=sys.stderr)
    try:
        subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"Clone failed: {exc}", file=sys.stderr)
        return None
    return dest.resolve()


def cmd_init() -> int:
    found = discover()
    registry = load_registry()
    added, updated, dupes = 0, 0, []
    for repo, paths in sorted(found.items()):
        # Keep whatever the maintainer already chose; otherwise take the first match.
        existing = registry.get(repo)
        keep = existing if existing in {str(p) for p in paths} else str(paths[0])
        if existing is None:
            added += 1
        elif existing != keep:
            updated += 1
        registry[repo] = keep
        print(f"  {repo:16} {keep}")
        if len(paths) > 1:
            dupes.append((repo, [str(p) for p in paths]))
    save_registry(registry)

    missing = sorted(KNOWN_REPOS - found.keys())
    print(f"\nRecorded {len(found)} repo(s) ({added} new, {updated} updated).")
    if missing:
        print(f"Not found locally: {', '.join(missing)} — clone them or run `set <repo> <path>`.")
    for repo, paths in dupes:
        print(f"\n⚠ Multiple checkouts of '{repo}' found — using the first. To pick another:")
        for p in paths:
            print(f"    repos.py set {repo} {p}")
    return 0


def cmd_get(repo: str) -> int:
    path = load_registry().get(repo)
    if path and Path(path).exists():
        print(path)
        return 0
    print(f"No recorded checkout for '{repo}'", file=sys.stderr)
    return 1


def cmd_set(repo: str, path: str) -> int:
    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        print(f"Not a directory: {resolved}", file=sys.stderr)
        return 1
    print(record(repo, resolved))
    return 0


def cmd_list() -> int:
    print(json.dumps(load_registry(), indent=2, sort_keys=True))
    return 0


def cmd_ensure(repo: str, *, allow_clone: bool) -> int:
    recorded = load_registry().get(repo)
    if recorded and Path(recorded).exists():
        print(recorded)
        return 0

    matches = discover(wanted={repo}).get(repo)
    if matches:
        print(record(repo, matches[0]))
        return 0

    if allow_clone:
        cloned = clone(repo)
        if cloned:
            print(record(repo, cloned))
            return 0

    print(
        f"Could not resolve '{repo}'. Set it with: repos.py set {repo} <path>, "
        f"or re-run with --clone to clone from GitHub.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="scan code roots and record every PostHog repo found")

    p_get = sub.add_parser("get", help="print the recorded path for a repo")
    p_get.add_argument("repo")

    p_set = sub.add_parser("set", help="record a path for a repo")
    p_set.add_argument("repo")
    p_set.add_argument("path")

    sub.add_parser("list", help="print the whole registry")

    p_ensure = sub.add_parser("ensure", help="resolve a repo path, recording the result")
    p_ensure.add_argument("repo")
    p_ensure.add_argument("--clone", action="store_true", help="clone from GitHub if not found locally")

    args = parser.parse_args()

    repo = getattr(args, "repo", None)
    if repo is not None and repo not in KNOWN_REPOS:
        print(f"Warning: '{repo}' is not a known repo key ({', '.join(sorted(KNOWN_REPOS))})", file=sys.stderr)

    if args.command == "init":
        return cmd_init()
    if args.command == "get":
        return cmd_get(args.repo)
    if args.command == "set":
        return cmd_set(args.repo, args.path)
    if args.command == "list":
        return cmd_list()
    if args.command == "ensure":
        return cmd_ensure(args.repo, allow_clone=args.clone)
    return 2


if __name__ == "__main__":
    sys.exit(main())
