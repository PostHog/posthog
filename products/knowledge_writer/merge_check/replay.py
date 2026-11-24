import os
import json
import base64
import hashlib
import argparse
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import requests
from anthropic import APIError

from posthog.egress.limiter.policies import Priority

from ..backend.facade.contracts import MergeCheckReport
from ..backend.logic.pull_requests import CompanionCheck, changed_files_for, decoded_text, head_texts, publication_check
from ..backend.logic.server_commit import BaseEntry, BaseTree, ancestor_directories
from ..backend.logic.writer_change import WriterChangeRefused, parse_writer_change
from ..backend.settings import DEFAULT_DOCS_PATHS, DocsSource, docs_source_for
from .check import run_merge_check
from .judge import judge_client
from .sources import (
    GitHubReader,
    LandedChange,
    PersonalTokenGitHub,
    UnexpectedGitHubResponse,
    landed_change,
    read_closed_pull_requests,
    read_github,
)

MAX_RECENT_MERGES = 100
EVAL_JOBS = 8
ERROR_MESSAGE_LIMIT = 200
GITHUB_CACHE_DIRECTORY = Path.home() / ".cache" / "posthog" / "knowledge-writer-eval" / "github"
CACHED_STATUS_CODES = frozenset({200, 404})
COMMIT_FILES_PER_PAGE = 100
PATCHED_FILE_STATUSES = frozenset({"modified", "changed"})
COMMIT_MAX_LISTED_FILES = 3000
EVAL_ROW_ERRORS = (requests.RequestException, httpx.HTTPError, APIError, UnexpectedGitHubResponse)
SCORED_CRITERION_BY_TRUTH_KEY = {
    "release_state": "release_state",
    "audience": "audience",
    "generated_docs_only": "generated_only",
    "no_public_page_fits": "no_public_page_fits",
}
UNSCORED_TRUTH_VALUES = frozenset({"not_applicable"})
PUBLISH_EVAL_MISTAKE_BY_TRUTH_AND_OUTCOME = {
    ("refuse", "publish"): "false_publish",
    ("refuse", "flag"): "false_publish",
    ("flag", "publish"): "missed_flag",
    ("publish", "refuse"): "false_refuse",
    ("flag", "refuse"): "false_refuse",
    ("publish", "flag"): "false_flag",
}
PUBLISH_EVAL_MISTAKES = ("false_publish", "missed_flag", "false_refuse", "false_flag")


def replay_command(arguments: argparse.Namespace) -> int:
    if arguments.eval:
        return eval_command(arguments)
    if arguments.publish_eval:
        return publish_eval_command(arguments.publish_eval)
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
    github = CachedGitHub(environment_github(), GITHUB_CACHE_DIRECTORY)
    source = docs_source_for(arguments.docs_repository)
    eval_rows = read_merges(arguments.eval)
    scored_rows: list[tuple[dict, MergeCheckReport]] = []
    failed_count = 0
    with httpx.Client(timeout=30) as http, ThreadPoolExecutor(max_workers=EVAL_JOBS) as pool:
        pending_checks = {
            pool.submit(
                check_eval_row,
                eval_row,
                github=github,
                http=http,
                source=source,
                writer_login=arguments.writer_login,
            ): eval_row
            for eval_row in eval_rows
        }
        try:
            for finished_check in as_completed(pending_checks):
                eval_row = pending_checks[finished_check]
                try:
                    report = finished_check.result()
                except EVAL_ROW_ERRORS as error:
                    failed_count += 1
                    error_line = {
                        "commit_sha": eval_row["commit_sha"],
                        "error": type(error).__name__,
                        "status_code": error_status_code(error),
                        "message": str(error)[:ERROR_MESSAGE_LIMIT],
                    }
                    print(json.dumps(error_line), flush=True)  # noqa: T201 — eval row
                    continue
                print(json.dumps(eval_line(eval_row, report)), flush=True)  # noqa: T201 — eval row
                if is_degraded(report):
                    failed_count += 1
                    continue
                scored_rows.append((eval_row, report))
        except BaseException:
            pool.shutdown(cancel_futures=True)
            raise
    print(json.dumps({"failed": failed_count, **eval_score(scored_rows)}))  # noqa: T201 — eval summary
    return 0


class CachedGitHub:
    def __init__(self, github: GitHubReader, directory: Path) -> None:
        self.github = github
        self.directory = directory
        self.page_entries_by_key: dict[str, dict] = {}

    def api_request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str | None = None,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        priority: Priority | None = None,
    ) -> requests.Response:
        if method != "GET":
            return self.github.api_request(
                method, path, endpoint=endpoint, params=params, headers=headers, priority=priority
            )
        request_key = cached_request_key(method, path, params, headers)
        is_listing_page = "page" in (params or {})
        cached_entry = (
            self.page_entries_by_key.get(request_key)
            if is_listing_page
            else read_cached_entry(self.directory / f"{request_key}.json")
        )
        if cached_entry is not None:
            return response_from_entry(cached_entry)
        response = self.github.api_request(
            method, path, endpoint=endpoint, params=params, headers=headers, priority=priority
        )
        if response.status_code not in CACHED_STATUS_CODES:
            return response
        if is_listing_page:
            self.page_entries_by_key[request_key] = entry_from_response(response)
            return response
        write_cached_entry(self.directory / f"{request_key}.json", entry_from_response(response))
        return response


def cached_request_key(
    method: str, path: str, params: dict[str, str | int] | None, headers: dict[str, str] | None
) -> str:
    request_identity = [method, path, sorted((params or {}).items()), sorted((headers or {}).items())]
    return hashlib.sha256(json.dumps(request_identity, default=str).encode()).hexdigest()


def entry_from_response(response: requests.Response) -> dict:
    return {
        "status_code": response.status_code,
        "reason": response.reason,
        "url": response.url,
        "encoding": response.encoding or "utf-8",
        "body": base64.b64encode(response.content).decode(),
    }


def response_from_entry(entry: dict) -> requests.Response:
    response = requests.Response()
    response.status_code = entry["status_code"]
    response.reason = entry["reason"]
    response.url = entry["url"]
    response.encoding = entry["encoding"]
    response._content = base64.b64decode(entry["body"])
    return response


def read_cached_entry(entry_path: Path) -> dict | None:
    if not entry_path.exists():
        return None
    return json.loads(entry_path.read_text())


def write_cached_entry(entry_path: Path, entry: dict) -> None:
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_path = tempfile.mkstemp(dir=entry_path.parent, suffix=".tmp")
    with os.fdopen(file_descriptor, "w") as temporary_file:
        json.dump(entry, temporary_file)
    os.replace(temporary_path, entry_path)


def check_eval_row(
    eval_row: dict,
    *,
    github: GitHubReader,
    http: httpx.Client,
    source: DocsSource,
    writer_login: str | None,
) -> MergeCheckReport:
    change = LandedChange(
        repository=eval_row["repository"],
        after=eval_row["commit_sha"],
        pull_request_number=eval_row["pull_request_number"],
    )
    with judge_client(change.after) as anthropic_client:
        return run_merge_check(
            change,
            is_final_attempt=True,
            github=github,
            http=http,
            anthropic_client=anthropic_client,
            source=source,
            writer_login=writer_login,
            is_pinned_to_merge=True,
        )


def error_status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        return status_code
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)


def is_degraded(report: MergeCheckReport) -> bool:
    return any(row.criterion == "facts" and row.value == "unavailable" for row in report.criteria)


def eval_line(eval_row: dict, report: MergeCheckReport) -> dict:
    return {
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


def publish_eval_command(labelled_commits_path: Path) -> int:
    github = CachedGitHub(environment_github(), GITHUB_CACHE_DIRECTORY)
    wrong_commits_by_kind: dict[str, list[str]] = {kind: [] for kind in PUBLISH_EVAL_MISTAKES}
    labelled_commits = [json.loads(line) for line in labelled_commits_path.read_text().splitlines() if line.strip()]
    failed_commits: list[str] = []
    for labelled_commit in labelled_commits:
        repository, commit_sha = labelled_commit["repository"], labelled_commit["commit_sha"]
        try:
            publication = commit_publication_check(github, repository, commit_sha)
        except EVAL_ROW_ERRORS as error:
            failed_commits.append(commit_sha)
            error_line = {
                "commit_sha": commit_sha,
                "error": type(error).__name__,
                "status_code": error_status_code(error),
                "message": str(error)[:ERROR_MESSAGE_LIMIT],
            }
            print(json.dumps(error_line), flush=True)  # noqa: T201 — eval row
            continue
        truth = labelled_commit["truth"]
        print(  # noqa: T201 — one eval row per labelled commit
            json.dumps(
                {
                    "commit_sha": commit_sha,
                    "truth": truth,
                    "outcome": publish_outcome(publication),
                    "refusal": publication.refusal,
                    "flags": list(publication.all_flags),
                }
            ),
            flush=True,
        )
        mistake = publish_eval_mistake(truth, publish_outcome(publication))
        if mistake is not None:
            wrong_commits_by_kind[mistake].append(commit_sha)
    summary = {
        "commits": len(labelled_commits),
        "failed": len(failed_commits),
        **{kind: len(shas) for kind, shas in wrong_commits_by_kind.items()},
    }
    print(json.dumps({**summary, "wrong_commits": wrong_commits_by_kind, "failed_commits": failed_commits}))  # noqa: T201 — eval summary
    return 0


def publish_outcome(publication: CompanionCheck) -> str:
    if publication.refusal is not None:
        return "refuse"
    return "flag" if publication.all_flags else "publish"


def publish_eval_mistake(truth: str, outcome: str) -> str | None:
    return PUBLISH_EVAL_MISTAKE_BY_TRUTH_AND_OUTCOME.get((truth, outcome))


def refused_publication(reason: str) -> CompanionCheck:
    return CompanionCheck(refusal=reason, flags=())


def commit_publication_check(github: GitHubReader, repository: str, commit_sha: str) -> CompanionCheck:
    commit_files, parent_tree_sha = commit_change(github, repository, commit_sha)
    try:
        change = parse_writer_change(writer_change_manifest(github, repository, commit_files))
    except WriterChangeRefused as refused:
        return refused_publication(refused.reason)
    if not change.paths:
        return refused_publication("no_changes")
    tree = parent_tree(github, repository, parent_tree_sha, change.paths)
    try:
        changed_files = changed_files_for(change, tree)
    except WriterChangeRefused as refused:
        return refused_publication(refused.reason)
    if changed_files is None:
        return refused_publication("unsafe_base_entry")
    return publication_check(
        changed_files, (DEFAULT_DOCS_PATHS.strip("/"),), repository, tree.texts, head_texts(change)
    )


def commit_change(github: GitHubReader, repository: str, commit_sha: str) -> tuple[list[dict], str]:
    commit_files: list[dict] = []
    page = 1
    while True:
        commit = read_github(
            github,
            f"/repos/{repository}/commits/{commit_sha}",
            endpoint="/repos/{owner}/{repo}/commits/{ref}",
            params={"page": page, "per_page": COMMIT_FILES_PER_PAGE},
        ).json()
        commit_files.extend(commit["files"])
        if len(commit["files"]) < COMMIT_FILES_PER_PAGE:
            break
        page += 1
    if len(commit_files) >= COMMIT_MAX_LISTED_FILES:
        raise UnexpectedGitHubResponse(f"GitHub lists at most {COMMIT_MAX_LISTED_FILES} files of a commit")
    parent = read_github(
        github,
        f"/repos/{repository}/git/commits/{commit['parents'][0]['sha']}",
        endpoint="/repos/{owner}/{repo}/git/commits/{commit_sha}",
    ).json()
    return commit_files, parent["tree"]["sha"]


def writer_change_manifest(github: GitHubReader, repository: str, compared_files: list[dict]) -> bytes:
    written = {
        compared_file["filename"]: blob_base64(github, repository, compared_file["sha"])
        for compared_file in compared_files
        if compared_file["status"] != "removed"
    }
    deleted = [
        compared_file["previous_filename"] if compared_file["status"] == "renamed" else compared_file["filename"]
        for compared_file in compared_files
        if compared_file["status"] in ("removed", "renamed")
    ]
    patches = {
        compared_file["filename"]: github_patch(compared_file)
        for compared_file in compared_files
        if compared_file["status"] in PATCHED_FILE_STATUSES
    }
    return json.dumps({"written": written, "deleted": deleted, "patches": patches}).encode()


def github_patch(compared_file: dict) -> str:
    patch = compared_file.get("patch", "" if compared_file["status"] == "changed" else None)
    if not isinstance(patch, str):
        raise UnexpectedGitHubResponse(f"GitHub omitted the patch of {compared_file['filename']}")
    return patch


def blob_base64(github: GitHubReader, repository: str, blob_sha: str) -> str:
    blob = read_github(
        github, f"/repos/{repository}/git/blobs/{blob_sha}", endpoint="/repos/{owner}/{repo}/git/blobs/{file_sha}"
    )
    return "".join(blob.json()["content"].split())


def parent_tree(github: GitHubReader, repository: str, root_tree_sha: str, paths: frozenset[str]) -> BaseTree:
    directories = sorted({directory for path in paths for directory in ancestor_directories(path)})
    tree_sha_by_directory = {"": root_tree_sha}
    listed_entries: dict[str, dict] = {}
    for directory in directories:
        tree_sha = tree_sha_by_directory.get(directory)
        if tree_sha is None:
            continue
        listing = read_github(
            github, f"/repos/{repository}/git/trees/{tree_sha}", endpoint="/repos/{owner}/{repo}/git/trees/{tree_sha}"
        )
        for entry in listing.json()["tree"]:
            entry_path = f"{directory}/{entry['path']}" if directory else entry["path"]
            listed_entries[entry_path] = entry
            if entry["type"] == "tree":
                tree_sha_by_directory[entry_path] = entry["sha"]
    every_path = paths | {directory for directory in directories if directory}
    return BaseTree(
        entries={
            path: BaseEntry(mode=int(listed_entries[path]["mode"], 8), oid=listed_entries[path]["sha"])
            if path in listed_entries
            else None
            for path in every_path
        },
        texts={path: parent_blob_text(github, repository, listed_entries.get(path)) for path in paths},
    )


def parent_blob_text(github: GitHubReader, repository: str, entry: dict | None) -> str | None:
    if entry is None or entry["type"] != "blob":
        return None
    return decoded_text(base64.b64decode(blob_base64(github, repository, entry["sha"])))


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
        "--eval", type=Path, help="score the merge check against a labelled jsonl such as evals/needs_docs.jsonl"
    )
    merge_source.add_argument(
        "--recent", type=recent_merge_count, help="replay the merged pull requests among the last N closed ones"
    )
    merge_source.add_argument(
        "--publish-eval",
        type=Path,
        help="score the publish check against docs commits labelled publish or refuse, such as evals/publish_check.jsonl",
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
    replay.set_defaults(handler=replay_command)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)
