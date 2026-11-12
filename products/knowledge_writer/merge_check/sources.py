import re
import fnmatch
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from posthog.egress.github.transport import github_request
from posthog.egress.limiter.policies import Priority

COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
NULL_COMMIT_SHA = "0" * 40
GITHUB_API_URL = "https://api.github.com"
GITHUB_EGRESS_SOURCE = "knowledge_writer"
DIFF_FILE_HEADER_PATTERN = re.compile(r"^diff --git a/\S+ b/(\S+)$")
MAX_READ_PAGES = 8
MAX_PAGE_SOURCE_CHARACTERS = 20_000
GENERATED_ATTRIBUTES = frozenset({"linguist-generated", "linguist-generated=true"})
TEST_PATH_PATTERN = re.compile(
    r"(^|/)(tests?|__tests__|__snapshots__)/|(^|/)test_[^/]+\.py$|\.(test|spec|stories)\.[jt]sx?$"
)


@dataclass(frozen=True)
class MergedPullRequest:
    number: int
    title: str
    url: str


@dataclass(frozen=True)
class LandedChange:
    repository: str
    after: str
    pull_request_number: int


class GitHubReader(Protocol):
    def api_request(
        self,
        method: str,
        path: str,
        *,
        endpoint: str | None = None,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        priority: Priority | None = None,
    ) -> requests.Response: ...


class PersonalTokenGitHub:
    def __init__(self, token: str) -> None:
        self.token = token

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
        return github_request(
            method,
            f"{GITHUB_API_URL}{path}",
            source=GITHUB_EGRESS_SOURCE,
            headers={**(headers or {}), "Authorization": f"Bearer {self.token}"},
            priority=priority or Priority.NORMAL,
            endpoint=endpoint,
            params=params,
            timeout=30,
        )


class UnexpectedGitHubResponse(Exception):
    pass


def read_github(
    github: GitHubReader,
    path: str,
    *,
    endpoint: str,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    priority: Priority = Priority.NORMAL,
) -> requests.Response:
    response = github.api_request("GET", path, endpoint=endpoint, params=params, headers=headers, priority=priority)
    response.raise_for_status()
    return response


def read_github_or_none(
    github: GitHubReader,
    path: str,
    *,
    endpoint: str,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response | None:
    response = github.api_request(
        "GET", path, endpoint=endpoint, params=params, headers=headers, priority=Priority.NORMAL
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response


def commit_sha_or_none(value: object) -> str | None:
    if not isinstance(value, str) or not COMMIT_SHA_PATTERN.match(value) or value == NULL_COMMIT_SHA:
        return None
    return value


def merged_pull_request_change(
    delivery: Mapping[str, Any], source_repositories: tuple[str, ...]
) -> LandedChange | None:
    repository = delivery.get("repository") or {}
    full_name = repository.get("full_name")
    listed = delivery.get("pull_request") or {}
    after = commit_sha_or_none(listed.get("merge_commit_sha"))
    if delivery.get("action") != "closed" or after is None or repository.get("private") is not False:
        return None
    if not isinstance(full_name, str) or full_name.lower() not in {name.lower() for name in source_repositories}:
        return None
    return landed_change(full_name, listed)


def landed_change(repository: str, listed: Mapping[str, Any]) -> LandedChange | None:
    after = commit_sha_or_none(listed.get("merge_commit_sha"))
    if after is None or not isinstance(listed.get("number"), int) or merged_pull_request(listed, after) is None:
        return None
    return LandedChange(repository=repository, after=after, pull_request_number=listed["number"])


def read_closed_pull_requests(
    github: GitHubReader, repository: str, *, page: int, per_page: int
) -> list[dict[str, Any]]:
    response = read_github(
        github,
        f"/repos/{repository}/pulls",
        endpoint="/repos/{owner}/{repo}/pulls",
        params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": per_page, "page": page},
    )
    return response.json()


def merged_pull_request(listed: Mapping[str, Any], commit_sha: str) -> MergedPullRequest | None:
    if not listed.get("merged_at") or listed.get("merge_commit_sha") != commit_sha:
        return None
    return MergedPullRequest(
        number=listed["number"],
        title=listed["title"],
        url=listed["html_url"],
    )


def read_pull_request(github: GitHubReader, repository: str, pull_request_number: int) -> dict[str, Any]:
    response = read_github(
        github,
        f"/repos/{repository}/pulls/{pull_request_number}",
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
    )
    return response.json()


def reached_default_branch(github: GitHubReader, repository: str, listed: Mapping[str, Any], commit_sha: str) -> bool:
    base = listed.get("base") or {}
    default_branch = (base.get("repo") or {}).get("default_branch")
    if not isinstance(default_branch, str):
        raise UnexpectedGitHubResponse(
            f"pull request for {commit_sha} in {repository} has no base repository default branch"
        )
    if base.get("ref") == default_branch:
        return True
    response = read_github(
        github,
        f"/repos/{repository}/compare/{default_branch}...{commit_sha}",
        endpoint="/repos/{owner}/{repo}/compare/{basehead}",
        params={"per_page": 1},
    )
    status = response.json().get("status")
    if not isinstance(status, str):
        raise UnexpectedGitHubResponse(f"compare of {default_branch}...{commit_sha} in {repository} returned no status")
    return status in ("behind", "identical")


def read_diff_by_path(github: GitHubReader, change: LandedChange) -> dict[str, str]:
    response = read_github(
        github,
        f"/repos/{change.repository}/commits/{change.after}",
        endpoint="/repos/{owner}/{repo}/commits/{sha}",
        headers={"Accept": "application/vnd.github.diff"},
    )
    diff_lines_by_path: dict[str, list[str]] = {}
    current_lines: list[str] | None = None
    for line in response.text.splitlines(keepends=True):
        header = DIFF_FILE_HEADER_PATTERN.match(line.rstrip("\n"))
        if header:
            current_lines = diff_lines_by_path.setdefault(header.group(1), [])
        if current_lines is not None:
            current_lines.append(line)
    return {path: "".join(lines) for path, lines in diff_lines_by_path.items()}


def is_test_path(path: str) -> bool:
    return TEST_PATH_PATTERN.search(path) is not None


def read_generated_path_patterns(github: GitHubReader, repository: str, commit_sha: str) -> list[str]:
    response = read_github_or_none(
        github,
        f"/repos/{repository}/contents/.gitattributes",
        endpoint="/repos/{owner}/{repo}/contents/{path}",
        params={"ref": commit_sha},
        headers={"Accept": "application/vnd.github.raw"},
    )
    if response is None:
        return []
    attribute_lines = [line.split() for line in response.text.splitlines() if not line.startswith("#")]
    return [
        fields[0].lstrip("/")
        for fields in attribute_lines
        if len(fields) > 1 and GENERATED_ATTRIBUTES & set(fields[1:])
    ]


def is_generated_path(path: str, generated_path_patterns: list[str]) -> bool:
    file_name = path.rpartition("/")[2]
    return any(
        fnmatch.fnmatchcase(path, pattern) or ("/" not in pattern and fnmatch.fnmatchcase(file_name, pattern))
        for pattern in generated_path_patterns
    )


def read_page_sources(
    github: GitHubReader, docs_repository: str, source_path_by_key: Mapping[str, str], *, docs_commit_sha: str | None
) -> dict[str, str]:
    page_text_by_key: dict[str, str] = {}
    for page_key, source_path in list(source_path_by_key.items())[:MAX_READ_PAGES]:
        response = read_github_or_none(
            github,
            f"/repos/{docs_repository}/contents/{source_path}",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
            params={"ref": docs_commit_sha} if docs_commit_sha else None,
            headers={"Accept": "application/vnd.github.raw"},
        )
        if response is None:
            continue
        page_text_by_key[page_key] = response.text[:MAX_PAGE_SOURCE_CHARACTERS]
    return page_text_by_key
