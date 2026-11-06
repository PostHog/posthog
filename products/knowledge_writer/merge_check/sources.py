import re
import fnmatch
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import requests

from posthog.egress.github.transport import github_request
from posthog.egress.limiter.policies import Priority

POSTHOG_REPOSITORY = "PostHog/posthog"
POSTHOG_MAINLINE = "master"
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
GITHUB_API_URL = "https://api.github.com"
GITHUB_EGRESS_SOURCE = "knowledge_writer"
SITEMAP_URL = "https://posthog.com/sitemap/sitemap-0.xml"
DOCS_URL_PREFIX = "https://posthog.com/docs/"
PUBLISHED_DOCS_DIRECTORY = "docs/published/docs"
PUBLISHED_DOCS_EXTENSIONS = (".md", ".mdx")
TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"MEMBER", "OWNER"})
SITEMAP_DOCS_URL_PATTERN = re.compile(r"<loc>(https://posthog\.com/docs/[^<]+)</loc>")
DIFF_FILE_HEADER_PATTERN = re.compile(r"^diff --git a/\S+ b/(\S+)$")
GENERATED_ATTRIBUTES = frozenset({"linguist-generated", "linguist-generated=true"})
TEST_PATH_PATTERN = re.compile(
    r"(^|/)(tests?|__tests__|__snapshots__)/|(^|/)test_[^/]+\.py$|\.(test|spec|stories)\.[jt]sx?$"
)


MAINLINE_COMPARE_STATUSES = frozenset({"behind", "identical"})


@dataclass(frozen=True)
class MergedPullRequest:
    number: int
    title: str
    url: str
    is_trusted_author: bool


@dataclass(frozen=True)
class MergedCommit:
    commit_sha: str
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


def read_github(
    github: GitHubReader,
    path: str,
    *,
    endpoint: str,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = github.api_request(
        "GET", path, endpoint=endpoint, params=params, headers=headers, priority=Priority.NORMAL
    )
    response.raise_for_status()
    return response


def merged_commit(pull_request: Mapping[str, Any]) -> MergedCommit | None:
    commit_sha = pull_request.get("merge_commit_sha")
    number = pull_request.get("number")
    if not pull_request.get("merged_at") or not isinstance(commit_sha, str) or not isinstance(number, int):
        return None
    if not COMMIT_SHA_PATTERN.match(commit_sha):
        return None
    return MergedCommit(commit_sha=commit_sha, pull_request_number=number)


def merged_pull_request(listed: Mapping[str, Any], commit_sha: str) -> MergedPullRequest | None:
    merge = merged_commit(listed)
    if merge is None or merge.commit_sha != commit_sha:
        return None
    return MergedPullRequest(
        number=merge.pull_request_number,
        title=listed["title"],
        url=listed["html_url"],
        is_trusted_author=listed.get("author_association") in TRUSTED_AUTHOR_ASSOCIATIONS,
    )


def read_merged_pull_request(github: GitHubReader, number: int, commit_sha: str) -> MergedPullRequest | None:
    response = read_github(
        github,
        f"/repos/{POSTHOG_REPOSITORY}/pulls/{number}",
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
    )
    return merged_pull_request(response.json(), commit_sha)


def find_merged_pull_request(github: GitHubReader, commit_sha: str) -> MergedPullRequest | None:
    response = read_github(
        github,
        f"/repos/{POSTHOG_REPOSITORY}/commits/{commit_sha}/pulls",
        endpoint="/repos/{owner}/{repo}/commits/{sha}/pulls",
    )
    merged = (merged_pull_request(listed, commit_sha) for listed in response.json())
    return next((pull_request for pull_request in merged if pull_request is not None), None)


def is_on_mainline(github: GitHubReader, commit_sha: str) -> bool:
    response = read_github(
        github,
        f"/repos/{POSTHOG_REPOSITORY}/compare/{POSTHOG_MAINLINE}...{commit_sha}",
        endpoint="/repos/{owner}/{repo}/compare/{basehead}",
        params={"per_page": 1},
    )
    return response.json().get("status") in MAINLINE_COMPARE_STATUSES


def read_commit_diff_by_path(github: GitHubReader, commit_sha: str) -> dict[str, str]:
    response = read_github(
        github,
        f"/repos/{POSTHOG_REPOSITORY}/commits/{commit_sha}",
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


def read_generated_path_patterns(github: GitHubReader, commit_sha: str) -> list[str]:
    response = github.api_request(
        "GET",
        f"/repos/{POSTHOG_REPOSITORY}/contents/.gitattributes",
        endpoint="/repos/{owner}/{repo}/contents/{path}",
        params={"ref": commit_sha},
        headers={"Accept": "application/vnd.github.raw"},
        priority=Priority.NORMAL,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
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


def is_published_from_repository(github: GitHubReader, commit_sha: str, page_path: str) -> bool:
    for extension in PUBLISHED_DOCS_EXTENSIONS:
        response = github.api_request(
            "GET",
            f"/repos/{POSTHOG_REPOSITORY}/contents/{PUBLISHED_DOCS_DIRECTORY}/{page_path.strip('/')}{extension}",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
            params={"ref": commit_sha},
            priority=Priority.NORMAL,
        )
        if response.status_code == 200:
            return True
        if response.status_code != 404:
            response.raise_for_status()
    return False


def read_docs_page_urls(http: httpx.Client) -> list[str]:
    response = http.get(SITEMAP_URL)
    response.raise_for_status()
    return SITEMAP_DOCS_URL_PATTERN.findall(response.text)
