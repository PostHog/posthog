"""Dependency-light JSON resolver entrypoint for non-Python consumers.

Reads newline-delimited repo-relative paths from stdin (or as argv) and writes a
JSON object keyed by normalized path to stdout::

    {"<path>": {"owners": [...], "status": "...", "slack": "...|null", "source": "...|null"}}

Kept off click on purpose (stdlib + pyyaml only) so a workflow can run it with
``python -m hogli_commands.owners`` after installing just pyyaml — no hogli, no
project sync. The click CLI (``hogli owners:resolve --json``) emits the identical
shape for dev use; both build it via ``resolution_to_wire`` so there is one format.
"""

from __future__ import annotations

import sys
import json

from .matcher import normalize_path
from .resolver import OwnersResolver, read_stdin_paths, resolution_to_wire


def main() -> None:
    args = sys.argv[1:]
    paths = args if args else read_stdin_paths()

    resolver = OwnersResolver()
    result = {normalize_path(path): resolution_to_wire(resolver.resolve(path)) for path in paths}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
