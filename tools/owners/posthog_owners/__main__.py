"""Dependency-light JSON resolver entrypoint for non-Python consumers.

Reads newline-delimited repo-relative paths from stdin (or as argv) and writes a
JSON object keyed by normalized path to stdout::

    {"<path>": {"owners": [...], "status": "...", "slack": "...|null", "source": "...|null"}}

``--purpose notifications`` resolves ``slack`` to the team's automation channel
(falls back to the people channel); the default is the people channel.

Kept off click on purpose (stdlib + pyyaml only) so a workflow can run it with
``python -m posthog_owners`` after installing just pyyaml — no hogli, no
project sync. The click CLI (``hogli owners:resolve --json``) emits the identical
shape for dev use; both build it via ``resolution_to_wire`` so there is one format.
"""

from __future__ import annotations

import sys
import json
import argparse
from typing import cast

from .matcher import normalize_path
from .resolver import DEFAULT_PURPOSE, OwnersResolver, Purpose, read_stdin_paths, resolution_to_wire


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m posthog_owners")
    parser.add_argument("--purpose", choices=["slack", "notifications"], default=DEFAULT_PURPOSE)
    parser.add_argument("paths", nargs="*")
    ns = parser.parse_args()
    paths = ns.paths or read_stdin_paths()

    resolver = OwnersResolver(purpose=cast("Purpose", ns.purpose))
    result = {normalize_path(path): resolution_to_wire(resolver.resolve(path)) for path in paths}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
