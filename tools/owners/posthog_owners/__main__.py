"""Dependency-light JSON resolver entrypoint for non-Python consumers.

Reads newline-delimited repo-relative paths from stdin (or as argv) and writes a
JSON object keyed by normalized path to stdout::

    {"<path>": {"owners": [...], "status": "...", "slack": "...|null", "source": "...|null"}}

``--purpose notifications`` resolves ``slack`` to the team's automation channel
(falls back to the people channel); the default is the people channel.

``--codeowners FILE`` switches to the other mode: it ignores the path arguments and writes a
CODEOWNERS projection of every tracked test file's ownership to FILE (``-`` for stdout), for a
consumer that reads CODEOWNERS and cannot read ``owners.yaml``. The GitHub organization comes from
``--org``, else from ``github_org`` in the root ``owners.yaml``.

``--repo-root`` names the directory holding the ownership files. Without it the
resolver locates the repo with ``git rev-parse``, which needs a real worktree; a
consumer that fetched only the ``owners.yaml`` / ``product.yaml`` files into a
scratch directory passes the flag instead.

Kept off click on purpose (stdlib + pyyaml only) so a workflow can run it with
``python -m posthog_owners`` after installing just pyyaml, with no project sync.
The click CLI (``owners resolve --json``) emits the identical shape; both build it
via ``resolution_to_wire`` so there is one format.
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path
from typing import cast

from .codeowners import package_dirs_from, project
from .matcher import normalize_path
from .resolver import DEFAULT_PURPOSE, OwnersResolver, Purpose, RepoRootNotFound, read_stdin_paths, resolution_to_wire


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m posthog_owners")
    parser.add_argument("--purpose", choices=["slack", "notifications"], default=DEFAULT_PURPOSE)
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Directory holding the ownership files; default: the enclosing git worktree",
    )
    parser.add_argument(
        "--codeowners",
        metavar="FILE",
        default=None,
        help="Write a CODEOWNERS projection of test-file ownership to FILE ('-' for stdout) and exit",
    )
    parser.add_argument(
        "--org",
        default=None,
        help="GitHub organization for --codeowners; default: github_org in the root owners.yaml",
    )
    parser.add_argument("paths", nargs="*")
    ns = parser.parse_args()
    # A root that is not a directory reads as a repo with no ownership files, so every path
    # answers unowned. An empty value is Path("."), which an unset "$VAR" would resolve
    # against the working directory instead of failing, so reject it before the conversion.
    if ns.repo_root is not None and not (ns.repo_root and Path(ns.repo_root).is_dir()):
        parser.error(f"--repo-root {ns.repo_root!r} is not a directory")
    repo_root = Path(ns.repo_root) if ns.repo_root is not None else None
    try:
        resolver = OwnersResolver(repo_root=repo_root, purpose=cast("Purpose", ns.purpose))
    except RepoRootNotFound as exc:
        parser.error(str(exc))

    if ns.codeowners:
        settings = resolver.settings()
        org = ns.org or settings.github_org
        if not org:
            parser.error(
                "--codeowners needs a GitHub organization: set github_org in the root owners.yaml or pass --org"
            )
        tracked = resolver.tracked_files()
        rendered = project(
            tracked,
            resolver,
            org=org,
            package_dirs=package_dirs_from(tracked),
            settings=settings.codeowners,
        ).render()
        if ns.codeowners == "-":
            sys.stdout.write(rendered)
        else:
            Path(ns.codeowners).write_text(rendered)
        return

    paths = ns.paths or read_stdin_paths()
    result = {normalize_path(path): resolution_to_wire(resolver.resolve(path)) for path in paths}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
