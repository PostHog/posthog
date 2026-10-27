import os
import sys
import json
import argparse
from pathlib import Path

import httpx
from anthropic import Anthropic
from pydantic import TypeAdapter

from ..backend.facade.contracts import MergeCheckReport
from .check import Checkouts, run_merge_check
from .sources import github_client

POST_ATTEMPTS = 2
report_json = TypeAdapter(MergeCheckReport)


def check_command(arguments: argparse.Namespace) -> int:
    checkouts = Checkouts(posthog=arguments.checkout, docs=arguments.docs_checkout) if arguments.checkout else None
    with github_client(os.environ["GITHUB_TOKEN"]) as github, httpx.Client(timeout=30) as http:
        report = run_merge_check(
            arguments.commit_sha, github=github, http=http, anthropic_client=Anthropic(), checkouts=checkouts
        )
        payload = report_json.dump_python(report, mode="json")
        print(json.dumps(payload))  # noqa: T201 — the CLI's output is the report
        if arguments.post:
            post_report(http, payload)
    return 0


def post_report(http: httpx.Client, payload: dict) -> None:
    for _attempt in range(POST_ATTEMPTS):
        response = http.post(
            os.environ["KNOWLEDGE_WRITER_VERDICTS_URL"],
            json=payload,
            headers={"Authorization": f"Bearer {os.environ['KNOWLEDGE_WRITER_API_TOKEN']}"},
        )
        if response.status_code < 500:
            break
    response.raise_for_status()


def replay_command(arguments: argparse.Namespace) -> int:
    merges = [json.loads(line) for line in arguments.merges.read_text().splitlines() if line.strip()]
    flagged = 0
    with github_client(os.environ["GITHUB_TOKEN"]) as github, httpx.Client(timeout=30) as http:
        for merge in merges:
            report = run_merge_check(
                merge["commit_sha"], github=github, http=http, anthropic_client=Anthropic(), checkouts=None
            )
            flagged += report.needs_docs
            page_hits = sorted(set(report.page_urls) & set(merge.get("page_urls", [])))
            row = {"commit_sha": merge["commit_sha"], "needs_docs": report.needs_docs, "page_hits": page_hits}
            print(json.dumps(row))  # noqa: T201 — one replay row per merge
    print(json.dumps({"merges": len(merges), "flagged": flagged}))  # noqa: T201 — replay summary
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="merge_check")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("commit_sha")
    check.add_argument("--checkout", type=Path)
    check.add_argument("--docs-checkout", type=Path)
    check.add_argument("--post", action="store_true")
    check.set_defaults(handler=check_command)
    replay = commands.add_parser("replay")
    replay.add_argument("merges", type=Path)
    replay.set_defaults(handler=replay_command)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
