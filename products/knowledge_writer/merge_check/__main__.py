import os
import sys
import json
import argparse
from pathlib import Path

import httpx

from .check import run_merge_check
from .judge import judge_client
from .sources import GitHubReader, LandedChange, PersonalTokenGitHub, landed_change, read_closed_pull_requests

MAX_RECENT_MERGES = 100


def replay_command(arguments: argparse.Namespace) -> int:
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"]
    flagged = 0
    github = PersonalTokenGitHub(github_token)
    with httpx.Client(timeout=30) as http:
        merges = (
            recent_merges(github, arguments.repository, arguments.recent)
            if arguments.recent
            else read_merges(arguments.merges)
        )
        for merge in merges:
            change = LandedChange(
                repository=arguments.repository,
                after=merge["commit_sha"],
                pull_request_number=merge["pull_request_number"],
            )
            with judge_client(merge["commit_sha"]) as anthropic_client:
                report = run_merge_check(
                    change,
                    is_final_attempt=True,
                    github=github,
                    http=http,
                    anthropic_client=anthropic_client,
                )
            flagged += report.needs_docs
            page_hits = sorted(set(report.page_urls) & set(merge.get("page_urls", [])))
            row = {"commit_sha": merge["commit_sha"], "needs_docs": report.needs_docs, "page_hits": page_hits}
            print(json.dumps(row))  # noqa: T201 — one replay row per merge
    print(json.dumps({"merges": len(merges), "flagged": flagged}))  # noqa: T201 — replay summary
    return 0


def read_merges(merges_path: Path) -> list[dict]:
    merges = [json.loads(line) for line in merges_path.read_text().splitlines() if line.strip()]
    if any("pull_request_number" not in merge for merge in merges):
        raise SystemExit(f"every row of {merges_path} needs commit_sha and pull_request_number")
    return merges


def recent_merges(github: GitHubReader, repository: str, count: int) -> list[dict]:
    closed_pull_requests = read_closed_pull_requests(github, repository, page=1, per_page=count)
    changes = (landed_change(repository, pull_request) for pull_request in closed_pull_requests)
    return [
        {"commit_sha": change.after, "pull_request_number": change.pull_request_number}
        for change in changes
        if change is not None
    ]


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
        "--recent", type=recent_merge_count, help="replay the merged pull requests among the last N closed ones"
    )
    replay.add_argument("--repository", default="PostHog/posthog", help="owner/name of the merged repository")
    replay.set_defaults(handler=replay_command)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
