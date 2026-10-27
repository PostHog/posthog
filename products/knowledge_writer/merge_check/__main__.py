import os
import sys
import json
import argparse
from pathlib import Path

import httpx
from anthropic import Anthropic

from .check import run_merge_check
from .sources import github_client


def replay_command(arguments: argparse.Namespace) -> int:
    merges = [json.loads(line) for line in arguments.merges.read_text().splitlines() if line.strip()]
    flagged = 0
    with github_client(os.environ["GITHUB_TOKEN"]) as github, httpx.Client(timeout=30) as http:
        for merge in merges:
            report = run_merge_check(merge["commit_sha"], github=github, http=http, anthropic_client=Anthropic())
            flagged += report.needs_docs
            page_hits = sorted(set(report.page_urls) & set(merge.get("page_urls", [])))
            row = {"commit_sha": merge["commit_sha"], "needs_docs": report.needs_docs, "page_hits": page_hits}
            print(json.dumps(row))  # noqa: T201 — one replay row per merge
    print(json.dumps({"merges": len(merges), "flagged": flagged}))  # noqa: T201 — replay summary
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="merge_check")
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("merges", type=Path)
    replay.set_defaults(handler=replay_command)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
