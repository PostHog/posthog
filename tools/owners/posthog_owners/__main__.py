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
from typing import cast

from .matcher import normalize_path
from .resolver import DEFAULT_PURPOSE, OwnersResolver, Purpose, read_stdin_paths, resolution_to_wire


def main() -> None:
    args = sys.argv[1:]
    purpose: Purpose = DEFAULT_PURPOSE
    if "--purpose" in args:
        flag = args.index("--purpose")
        value = args[flag + 1] if flag + 1 < len(args) else ""
        if value not in ("slack", "notifications"):
            sys.exit(f"--purpose must be 'slack' or 'notifications', got {value!r}")
        purpose = cast(Purpose, value)
        args = args[:flag] + args[flag + 2 :]
    paths = args if args else read_stdin_paths()

    resolver = OwnersResolver(purpose=purpose)
    result = {normalize_path(path): resolution_to_wire(resolver.resolve(path)) for path in paths}
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
