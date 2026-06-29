#!/usr/bin/env python3
"""Resolve and remember local checkouts of the PostHog repos that Surveys spans.

GitHub is the source of truth for where the code lives; this script is a per-maintainer
cache of where each repo was cloned, stored at ~/.config/posthog-surveys/repos.json, so a
checkout is found once and reused instead of re-cloned every session.

Usage:
    repos.py get <repo>              Print the recorded path (exit 1 if unknown/missing).
    repos.py set <repo> <path>       Record an absolute path for a repo.
    repos.py list                    Print the whole registry as JSON.
    repos.py ensure <repo>           Resolve a path: registry -> local search -> clone,
                                     record the result, and print it.

Known repo keys: posthog, posthog-js, posthog-ios, posthog-android, posthog-flutter,
posthog.com (keys match GitHub repo names; web + React Native both live in posthog-js).
"""

from __future__ import annotations

import argparse
import json
import os
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

# Where to look for an existing checkout before offering to clone.
SEARCH_PARENTS = [
    Path.cwd().parent,
    Path.home() / "src",
    Path.home() / "code",
    Path.home() / "dev",
    Path.home() / "projects",
]


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


def is_repo_checkout(path: Path, repo: str) -> bool:
    """A directory is a match if it's a git repo whose origin is PostHog/<repo>,
    falling back to a plain name match when origin can't be read."""
    if not path.is_dir():
        return False
    try:
        origin = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        origin = ""
    if origin:
        normalized = origin.lower().rstrip("/").removesuffix(".git")
        return normalized.endswith(f"posthog/{repo.lower()}")
    return path.name == repo


def search_local(repo: str) -> Path | None:
    for parent in SEARCH_PARENTS:
        candidate = parent / repo
        if is_repo_checkout(candidate, repo):
            return candidate.resolve()
    return None


def clone(repo: str) -> Path | None:
    dest = Path.home() / "src" / repo
    if dest.exists():
        return dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/PostHog/{repo}"
    print(f"Cloning {url} -> {dest} ...", file=sys.stderr)
    try:
        subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"Clone failed: {exc}", file=sys.stderr)
        return None
    return dest.resolve()


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

    found = search_local(repo)
    if found:
        print(record(repo, found))
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
