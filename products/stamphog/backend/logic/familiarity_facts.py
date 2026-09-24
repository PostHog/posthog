"""Author-familiarity facts read from GitHub, for the engine's familiarity signal.

The engine (``packages/pr-approval-agent/familiarity.py``) measures how familiar a PR author is
with the code the PR changes: who last touched each changed base-side line, and which of the
author's merged PRs touched the changed paths. Read from git, that needs the full history in the
sandbox checkout. The server reads the same facts from GitHub's GraphQL API instead, so the
sandbox can clone without history.

This module only collects raw facts. The engine matches commits to the author, counts, and bands,
so the band rules live in one place. Everything here is best effort: any failure yields no facts,
and the engine then leaves the signal absent, which can never make a review stricter.
"""

from __future__ import annotations

import re
import time
from bisect import bisect_left
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

import structlog

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError

from products.stamphog.backend.logic.github_client import StamphogGitHubClient

logger = structlog.get_logger(__name__)

# Mirrors the lockfile names of DEPENDENCY_ECOSYSTEMS in the engine's gates.py, which familiarity.py
# keeps out of blame. Update both. Matched against the lowercased basename, like the engine.
LOCKFILE_NAMES = frozenset(
    {
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "npm-shrinkwrap.json",
        "uv.lock",
        "poetry.lock",
        "pipfile.lock",
        "gemfile.lock",
        "composer.lock",
        "cargo.lock",
        "go.sum",
    }
)

# Mirror _MAX_CHANGED_LINES_PER_FILE and _MAX_BLAME_FILES in the engine's familiarity.py, which the
# backend cannot import.
MAX_CHANGED_LINES_PER_FILE = 2000
MAX_CONSIDERED_FILES = 30

# The engine's git path reads history with `--since=18.months`.
_HISTORY_WINDOW = timedelta(days=548)

# The whole collection must finish inside this budget, or the run goes on without facts. It runs
# while the rest of the context is fetched, so it only adds latency when GitHub is slow.
_BUDGET_SECONDS = 15
# GitHub aborts a GraphQL request after about ten seconds. A blame that takes longer than a few
# seconds belongs to a file with a very long history, usually a generated one, and the engine counts
# a missing blame as not owned, so it is cheaper to give up on that file early.
_BLAME_TIMEOUT_SECONDS = 6
_HISTORY_TIMEOUT_SECONDS = 10
_MAX_PARALLEL_REQUESTS = 8
# History aliases per request. GitHub resolves the aliases of one request one after another, so a
# large batch runs into the same ten-second abort as a large blame.
_HISTORY_PATHS_PER_REQUEST = 10
# A directory's history counts prior PRs, and the engine's MODERATE band needs only a few, so the
# newest 100 commits per directory are enough. A file's history only answers "did the author touch it".
_DIRECTORY_HISTORY_COMMITS = 100
_FILE_HISTORY_COMMITS = 1

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


def is_lockfile(path: str) -> bool:
    return PurePosixPath(path).name.lower() in LOCKFILE_NAMES


def select_considered_files(files: list[dict]) -> list[dict]:
    """The changed files the engine's familiarity reads, from the files API payload.

    Mirrors ``_select_considered_files`` in the engine's familiarity.py: no binaries, no
    lockfiles, no file over the changed-line bound, and the largest files first up to the cap.
    GitHub reports a binary as zero changed lines, and ``changes`` is the engine's
    ``changed_lines``. A file that is left out here but kept by the engine gets no blame facts,
    and the engine then counts its lines as not owned.
    """
    eligible = [
        entry
        for entry in files
        if 0 < entry.get("changes", 0) <= MAX_CHANGED_LINES_PER_FILE and not is_lockfile(entry.get("filename", ""))
    ]
    eligible.sort(key=lambda entry: entry.get("changes", 0), reverse=True)
    return eligible[:MAX_CONSIDERED_FILES]


def base_side_lines(patch: str) -> list[int]:
    """The base-side line numbers a file patch removes or replaces (its ``-`` lines)."""
    lines: list[int] = []
    old_line = 0
    in_hunk = False
    for line in patch.splitlines():
        hunk = _HUNK_RE.match(line)
        if hunk:
            in_hunk = True
            old_line = int(hunk.group(1))
            continue
        if not in_hunk or not line:
            continue
        if line[0] == "-":
            lines.append(old_line)
            old_line += 1
        elif line[0] == " ":
            old_line += 1
    return lines


def _history_directories(considered: list[dict]) -> list[str]:
    """Directory pathspecs for the prior-PR history queries.

    Mirrors the engine: prior PRs are counted over the parent directory of each changed file, and a
    root-level file stands for itself.
    """
    directories: set[str] = set()
    for entry in considered:
        filename = entry.get("filename") or ""
        parent = str(PurePosixPath(filename).parent)
        directories.add(filename if parent == "." else parent)
    return sorted(directories)


def _history_file_paths(considered: list[dict]) -> list[str]:
    """File paths for the previously-modified history queries, both paths of a rename included."""
    file_paths: set[str] = set()
    for entry in considered:
        file_paths.update(path for path in (entry.get("filename"), entry.get("previous_filename")) if path)
    return sorted(file_paths)


def _commit_fact(node: dict) -> tuple[str, dict] | None:
    oid = node.get("oid")
    if not isinstance(oid, str):
        return None
    author = node.get("author") or {}
    try:
        committed_at = int(datetime.fromisoformat(str(node.get("committedDate"))).timestamp())
    except ValueError:
        committed_at = 0
    return oid, {
        "login": (author.get("user") or {}).get("login"),
        "name": author.get("name"),
        "subject": node.get("messageHeadline") or "",
        "committed_at": committed_at,
    }


def _ranges_touching(blame_ranges: list[dict], lines: list[int]) -> list[dict]:
    """The blame ranges that cover at least one of the sorted ``lines``."""
    touching: list[dict] = []
    for blame_range in blame_ranges:
        start = int(blame_range.get("startingLine") or 0)
        end = int(blame_range.get("endingLine") or 0)
        index = bisect_left(lines, start)
        if index < len(lines) and lines[index] <= end:
            touching.append({"start": start, "end": end, "commit": blame_range.get("commit") or {}})
    return touching


@frozen
class ReviewHistory:
    """What the server learned about the PR's history before the review.

    ``familiarity_facts`` is None when collection failed or was not wanted. The engine then
    leaves the familiarity signal absent.
    """

    merge_base_sha: str | None
    familiarity_facts: dict | None


class FamiliarityFactsCollector:
    """Reads blame and author history from GitHub at the PR's merge base."""

    def __init__(self, client: StamphogGitHubClient, repo: str, merge_base_sha: str, author_node_id: str) -> None:
        self.client = client
        self.repo = repo
        self.merge_base_sha = merge_base_sha
        self.author_node_id = author_node_id

    def _blame(self, path: str) -> list[dict]:
        return self.client.get_blame_ranges(self.repo, self.merge_base_sha, path, timeout=_BLAME_TIMEOUT_SECONDS)

    def _history(self, paths: list[str], first: int, since: str) -> dict[str, list[dict]]:
        return self.client.get_author_history(
            self.repo,
            self.merge_base_sha,
            self.author_node_id,
            paths,
            since=since,
            first=first,
            timeout=_HISTORY_TIMEOUT_SECONDS,
        )

    def collect(self, considered: list[dict], deadline: float) -> dict | None:
        """The familiarity facts for the considered files, or None on any failure but a per-file blame one.

        A file whose blame fails, or does not finish inside the budget, is left out, and the engine
        counts its lines as not owned, the same as a failed `git blame`. A rate limit or a failed or
        unfinished history query drops all facts, because a partial history reads as an author with
        fewer prior PRs.
        """
        blame_targets: dict[str, list[int]] = {}
        for entry in considered:
            patch = entry.get("patch")
            if entry.get("status") == "added" or not patch:
                continue
            lines = sorted(set(base_side_lines(patch)))
            if lines:
                blame_targets[entry.get("previous_filename") or entry["filename"]] = lines

        directories = _history_directories(considered)
        file_paths = _history_file_paths(considered)
        since = (datetime.now(UTC) - _HISTORY_WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
        history_jobs: list[tuple[list[str], int]] = [
            (chunk, first)
            for paths, first in ((directories, _DIRECTORY_HISTORY_COMMITS), (file_paths, _FILE_HISTORY_COMMITS))
            for chunk in (
                paths[index : index + _HISTORY_PATHS_PER_REQUEST]
                for index in range(0, len(paths), _HISTORY_PATHS_PER_REQUEST)
            )
        ]

        executor = ThreadPoolExecutor(max_workers=_MAX_PARALLEL_REQUESTS, thread_name_prefix="stamphog-familiarity")
        try:
            # History goes first, so up to thirty slow blame requests cannot hold it in the queue.
            history_futures = [executor.submit(self._history, paths, first, since) for paths, first in history_jobs]
            blame_futures = {path: executor.submit(self._blame, path) for path in blame_targets}
            futures: list[Future[Any]] = [*history_futures, *blame_futures.values()]
            _done, pending = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if any(future in pending for future in history_futures):
            logger.warning("stamphog_familiarity_facts_timed_out", repo=self.repo)
            return None
        finished_blame = {path: future for path, future in blame_futures.items() if future not in pending}
        return self._assemble(blame_targets, finished_blame, history_futures, directories)

    def _assemble(
        self,
        blame_targets: dict[str, list[int]],
        blame_futures: dict[str, Future[list[dict]]],
        history_futures: list[Future[dict[str, list[dict]]]],
        directories: list[str],
    ) -> dict | None:
        commits: dict[str, dict] = {}

        def remember(node: dict) -> str | None:
            fact = _commit_fact(node)
            if fact is None:
                return None
            commits[fact[0]] = fact[1]
            return fact[0]

        blame: dict[str, list[dict]] = {}
        for path, future in blame_futures.items():
            error = future.exception()
            if isinstance(error, GitHubRateLimitError | GitHubEgressBudgetExhausted):
                logger.warning("stamphog_familiarity_facts_rate_limited", repo=self.repo)
                return None
            if error is not None:
                logger.info("stamphog_familiarity_blame_failed", repo=self.repo, error=type(error).__name__)
                continue
            blame[path] = [
                {"start": touching["start"], "end": touching["end"], "oid": oid}
                for touching in _ranges_touching(future.result(), blame_targets[path])
                if (oid := remember(touching["commit"])) is not None
            ]

        path_history: set[str] = set()
        file_history: dict[str, list[str]] = {}
        wanted_directories = set(directories)
        for history_future in history_futures:
            error = history_future.exception()
            if error is not None:
                logger.warning("stamphog_familiarity_history_failed", repo=self.repo, error=type(error).__name__)
                return None
            for path, nodes in history_future.result().items():
                oids = [oid for node in nodes if (oid := remember(node)) is not None]
                # A root-level file is both a directory pathspec and a file path, so it can land in both.
                if path in wanted_directories:
                    path_history.update(oids)
                file_history.setdefault(path, []).extend(oids)
        return {
            "commits": commits,
            "blame": blame,
            "path_history": sorted(path_history),
            "file_history": file_history,
        }


def fetch_review_history(
    client: StamphogGitHubClient, repo: str, pr: dict, files: list[dict], *, include_familiarity: bool
) -> ReviewHistory:
    """The PR's merge base and, when wanted, the author-familiarity facts. Never raises."""
    deadline = time.monotonic() + _BUDGET_SECONDS
    base_sha = (pr.get("base") or {}).get("sha") or ""
    head_sha = (pr.get("head") or {}).get("sha") or ""
    try:
        merge_base_sha = client.get_merge_base_sha(repo, base_sha, head_sha) if base_sha and head_sha else None
    except Exception:
        logger.warning("stamphog_merge_base_lookup_failed", repo=repo, exc_info=True)
        merge_base_sha = None

    author_node_id = (pr.get("user") or {}).get("node_id")
    if not include_familiarity or merge_base_sha is None or not author_node_id:
        return ReviewHistory(merge_base_sha=merge_base_sha, familiarity_facts=None)
    try:
        collector = FamiliarityFactsCollector(client, repo, merge_base_sha, str(author_node_id))
        facts = collector.collect(select_considered_files(files), deadline)
    except Exception:
        logger.warning("stamphog_familiarity_facts_failed", repo=repo, exc_info=True)
        facts = None
    return ReviewHistory(merge_base_sha=merge_base_sha, familiarity_facts=facts)
