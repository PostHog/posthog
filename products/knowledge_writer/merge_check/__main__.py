import os
import sys
import json
import argparse
from pathlib import Path

from .check import run_merge_check
from .judge import judge_client
from .sources import POSTHOG_MAINLINE, POSTHOG_REPOSITORY, GitHubReader, MergeSubject, PersonalTokenGitHub, read_github

MAX_RECENT_MERGES = 100


def replay_command(arguments: argparse.Namespace) -> int:
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"]
    flagged = 0
    github = PersonalTokenGitHub(github_token)
    merges = recent_master_merges(github, arguments.recent) if arguments.recent else read_merges(arguments.merges)
    for merge in merges:
        with judge_client(merge["commit_sha"]) as anthropic_client:
            report = run_merge_check(
                MergeSubject(repository=POSTHOG_REPOSITORY, commit_sha=merge["commit_sha"]),
                github=github,
                find_docs_page_urls=lambda _docs_query: [],
                anthropic_client=anthropic_client,
            )
        flagged += report.needs_docs
        row = {
            "commit_sha": merge["commit_sha"],
            "needs_docs": report.needs_docs,
            "reason": report.reason,
            "docs_query": report.docs_query,
        }
        print(json.dumps(row))  # noqa: T201 — one replay row per merge
    print(json.dumps({"merges": len(merges), "flagged": flagged}))  # noqa: T201 — replay summary
    return 0


def read_merges(merges_path: Path) -> list[dict]:
    return [json.loads(line) for line in merges_path.read_text().splitlines() if line.strip()]


def recent_master_merges(github: GitHubReader, count: int) -> list[dict]:
    response = read_github(
        github,
        f"/repos/{POSTHOG_REPOSITORY}/commits",
        endpoint="/repos/{owner}/{repo}/commits",
        params={"sha": POSTHOG_MAINLINE, "per_page": count},
    )
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
