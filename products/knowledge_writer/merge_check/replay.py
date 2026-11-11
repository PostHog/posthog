import os
import json
import argparse
from pathlib import Path

import httpx
import requests
from anthropic import APIError

from ..backend.facade.contracts import MergeCheckReport
from ..backend.settings import docs_source_for
from .check import merge_reports_by_variant, run_merge_check
from .judge import Variant, judge_client
from .sources import (
    GitHubReader,
    LandedChange,
    PersonalTokenGitHub,
    UnexpectedGitHubResponse,
    landed_change,
    read_closed_pull_requests,
)

MAX_RECENT_MERGES = 100
DEGRADED_REASONS = frozenset({"facts_unavailable", "page_check_unavailable"})
EVAL_ROW_ERRORS = (requests.RequestException, httpx.HTTPError, APIError, UnexpectedGitHubResponse)
SCORED_CRITERION_BY_TRUTH_KEY = {
    "release_state": "release_state",
    "audience": "audience",
    "generated_docs_only": "generated_only",
    "no_public_page_fits": "no_public_page_fits",
}
UNSCORED_TRUTH_VALUES = frozenset({"not_applicable"})


def replay_command(arguments: argparse.Namespace) -> int:
    if arguments.eval:
        return eval_command(arguments)
    flagged = 0
    github = environment_github()
    source = docs_source_for(arguments.docs_repository)
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
                    source=source,
                    writer_login=arguments.writer_login,
                    variant=arguments.variant or Variant.JUDGE,
                )
            flagged += report.needs_docs
            page_hits = sorted(set(report.page_urls) & set(merge.get("page_urls", [])))
            row = {"commit_sha": merge["commit_sha"], "needs_docs": report.needs_docs, "page_hits": page_hits}
            print(json.dumps(row))  # noqa: T201 — one replay row per merge
    print(json.dumps({"merges": len(merges), "flagged": flagged}))  # noqa: T201 — replay summary
    return 0


def environment_github() -> PersonalTokenGitHub:
    return PersonalTokenGitHub(os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"])


def eval_command(arguments: argparse.Namespace) -> int:
    github = environment_github()
    source = docs_source_for(arguments.docs_repository)
    variants = (arguments.variant,) if arguments.variant else tuple(Variant)
    eval_rows = read_merges(arguments.eval)
    scored_rows_by_variant: dict[Variant, list[tuple[dict, MergeCheckReport]]] = {variant: [] for variant in variants}
    failed_count_by_variant = dict.fromkeys(variants, 0)
    with httpx.Client(timeout=30) as http:
        for eval_row in eval_rows:
            change = LandedChange(
                repository=eval_row["repository"],
                after=eval_row["commit_sha"],
                pull_request_number=eval_row["pull_request_number"],
            )
            try:
                with judge_client(change.after) as anthropic_client:
                    report_by_variant = merge_reports_by_variant(
                        change,
                        is_final_attempt=True,
                        github=github,
                        http=http,
                        anthropic_client=anthropic_client,
                        source=source,
                        writer_login=arguments.writer_login,
                        variants=variants,
                        is_pinned_to_merge=True,
                    )
            except EVAL_ROW_ERRORS as error:
                for variant in variants:
                    failed_count_by_variant[variant] += 1
                print(json.dumps({"commit_sha": change.after, "error": type(error).__name__}))  # noqa: T201 — eval row
                continue
            for variant, report in report_by_variant.items():
                print(json.dumps(eval_line(variant, eval_row, report)))  # noqa: T201 — one eval row per variant
                if is_degraded(report):
                    failed_count_by_variant[variant] += 1
                    continue
                scored_rows_by_variant[variant].append((eval_row, report))
    for variant, scored_rows in scored_rows_by_variant.items():
        summary = {"variant": variant, "failed": failed_count_by_variant[variant], **eval_score(scored_rows)}
        print(json.dumps(summary))  # noqa: T201 — eval summary per variant
    return 0


def is_degraded(report: MergeCheckReport) -> bool:
    has_unavailable_facts = any(row.criterion == "facts" and row.value == "unavailable" for row in report.criteria)
    return has_unavailable_facts or report.reason in DEGRADED_REASONS


def eval_line(variant: Variant, eval_row: dict, report: MergeCheckReport) -> dict:
    return {
        "variant": variant,
        "commit_sha": report.commit_sha,
        "truth": eval_row["truth"],
        "needs_docs": report.needs_docs,
        "low_confidence": report.low_confidence,
        "reason": report.reason,
    }


def eval_score(scored_rows: list[tuple[dict, MergeCheckReport]]) -> dict:
    outcome_counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    agreement_counts = {criterion: [0, 0] for criterion in SCORED_CRITERION_BY_TRUTH_KEY.values()}
    for eval_row, report in scored_rows:
        outcome_counts[outcome_label(eval_row["truth"], report.needs_docs)] += 1
        report_value_by_criterion = {row.criterion: row.value for row in report.criteria}
        for truth_key, criterion in SCORED_CRITERION_BY_TRUTH_KEY.items():
            truth_value = criterion_text(eval_row["criteria"].get(truth_key))
            report_value = report_value_by_criterion.get(criterion)
            if report_value is None or truth_value is None or truth_value in UNSCORED_TRUTH_VALUES:
                continue
            agreement_counts[criterion][0] += report_value == truth_value
            agreement_counts[criterion][1] += 1
    flagged = outcome_counts["tp"] + outcome_counts["fp"]
    needing_docs = outcome_counts["tp"] + outcome_counts["fn"]
    return {
        **outcome_counts,
        "precision": round(outcome_counts["tp"] / flagged, 3) if flagged else None,
        "recall": round(outcome_counts["tp"] / needing_docs, 3) if needing_docs else None,
        "agreement": {
            criterion: round(agreed / compared, 3) if compared else None
            for criterion, (agreed, compared) in agreement_counts.items()
        },
        "low_confidence": sum(report.low_confidence for _eval_row, report in scored_rows),
    }


def outcome_label(truth: bool, needs_docs: bool) -> str:
    if truth:
        return "tp" if needs_docs else "fn"
    return "fp" if needs_docs else "tn"


def criterion_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def read_merges(merges_path: Path) -> list[dict]:
    merges = [json.loads(line) for line in merges_path.read_text().splitlines() if line.strip()]
    if any(not isinstance(merge.get("pull_request_number"), int) for merge in merges):
        raise SystemExit(f"every row of {merges_path} needs commit_sha and an integer pull_request_number")
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
        "--eval", type=Path, help="score each variant against a labelled jsonl such as evals/needs_docs.jsonl"
    )
    merge_source.add_argument(
        "--recent", type=recent_merge_count, help="replay the merged pull requests among the last N closed ones"
    )
    replay.add_argument("--repository", default="PostHog/posthog", help="owner/name of the merged repository")
    replay.add_argument(
        "--docs-repository",
        default=os.environ.get("KNOWLEDGE_WRITER_DOCS_REPOSITORY") or "PostHog/posthog.com",
        help="owner/name of the repository the docs pages are built from",
    )
    replay.add_argument(
        "--writer-login", help="GitHub login whose docs pull requests block a verdict, such as app-slug[bot]"
    )
    replay.add_argument(
        "--variant",
        type=Variant,
        choices=list(Variant),
        help="judge decides with one model call; rules decides from quoted facts and a page check. "
        "Replay defaults to judge; --eval scores every variant unless one is named",
    )
    replay.set_defaults(handler=replay_command)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)
