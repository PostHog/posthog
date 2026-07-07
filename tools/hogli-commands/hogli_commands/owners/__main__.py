"""Dependency-light JSON resolver entrypoint for non-Python consumers.

Reads newline-delimited repo-relative paths from stdin (or as argv) and writes a
JSON object keyed by normalized path to stdout::

    {"<path>": {"owners": [...], "status": "...", "slack": "...|null", "source": "...|null"}}

Kept off click on purpose (stdlib + pyyaml only) so a workflow can run it with
``python -m hogli_commands.owners`` after installing just pyyaml — no hogli, no
project sync. The click CLI (``hogli owners:resolve --json``) emits the identical
shape for dev use; both go through the same resolver so there is one semantics.
"""

from __future__ import annotations

import sys
import json

from .matcher import normalize_path
from .resolver import OwnersResolver


def main() -> None:
    args = sys.argv[1:]
    paths = args if args else [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]

    resolver = OwnersResolver()
    result = {}
    for path in paths:
        r = resolver.resolve(path)
        result[normalize_path(path)] = {
            "owners": r.owners or [],
            "status": r.status,
            "slack": r.slack,
            "source": r.source,
        }
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
