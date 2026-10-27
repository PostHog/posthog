import os
import sys
import json
import argparse
from pathlib import Path

import httpx
from anthropic import Anthropic

from .check import run_merge_check
from .sources import POSTHOG_REPOSITORY, github_client

MAX_RECENT_MERGES = 100


def replay_command(arguments: argparse.Namespace) -> int:
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"]
    flagged = 0
    with github_client(github_token) as github, httpx.Client(timeout=30) as http:
        merges = recent_master_merges(github, arguments.recent) if arguments.recent else read_merges(arguments.merges)
        for merge in merges:
            report = run_merge_check(merge["commit_sha"], github=github, http=http, anthropic_client=Anthropic())
            flagged += report.needs_docs
            page_hits = sorted(set(report.page_urls) & set(merge.get("page_urls", [])))
            row = {"commit_sha": merge["commit_sha"], "needs_docs": report.needs_docs, "page_hits": page_hits}
            print(json.dumps(row))  # noqa: T201 — one replay row per merge
    print(json.dumps({"merges": len(merges), "flagged": flagged}))  # noqa: T201 — replay summary
    return 0


def read_merges(merges_path: Path) -> list[dict]:
    return [json.loads(line) for line in merges_path.read_text().splitlines() if line.strip()]


def recent_master_merges(github: httpx.Client, count: int) -> list[dict]:
    response = github.get(f"/repos/{POSTHOG_REPOSITORY}/commits", params={"sha": "master", "per_page": count})
    response.raise_for_status()
    return [{"commit_sha": commit["sha"]} for commit in response.json()]


def recent_merge_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= MAX_RECENT_MERGES:
        raise argparse.ArgumentTypeError(f"pick between 1 and {MAX_RECENT_MERGES} merges")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="merge_check")
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay")
    merge_source = replay.add_mutually_exclusive_group(required=True)
    merge_source.add_argument("merges", type=Path, nargs="?")
    merge_source.add_argument(
        "--recent", type=recent_merge_count, help="replay the last N PostHog/posthog master merges"
    )
    replay.set_defaults(handler=replay_command)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
