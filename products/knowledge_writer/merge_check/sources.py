import re
import fnmatch
from dataclasses import dataclass
from typing import Protocol

import requests

from posthog.egress.github.transport import github_request
from posthog.egress.limiter.policies import Priority

POSTHOG_REPOSITORY = "PostHog/posthog"
POSTHOG_MAINLINE = "master"
GITHUB_API_URL = "https://api.github.com"
GITHUB_EGRESS_SOURCE = "knowledge_writer"
DOCS_URL_PREFIX = "https://posthog.com/docs/"
PUBLISHED_DOCS_DIRECTORY = "docs/published/docs"
PUBLISHED_DOCS_EXTENSIONS = (".md", ".mdx")
TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"MEMBER", "OWNER"})
DIFF_FILE_HEADER_PATTERN = re.compile(r"^diff --git a/\S+ b/(\S+)$")
GENERATED_ATTRIBUTES = frozenset({"linguist-generated", "linguist-generated=true"})
TEST_PATH_PATTERN = re.compile(
    r"(^|/)(tests?|__tests__|__snapshots__)/|(^|/)test_[^/]+\.py$|\.(test|spec|stories)\.[jt]sx?$"
)


@dataclass(frozen=True)
class MergeSubject:
    repository: str
    commit_sha: str | None = None
    pull_request_number: int | None = None
    note: str = ""


@dataclass(frozen=True)
class MergedPullRequest:
    number: int
    title: str
    url: str
    merge_commit_sha: str
    is_trusted_author: bool


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


def read_merged_pull_request(github: GitHubReader, subject: MergeSubject) -> MergedPullRequest | None:
    if subject.pull_request_number is not None:
        return read_pull_request_by_number(github, subject.repository, subject.pull_request_number)
    if subject.commit_sha is None:
        return None
    return find_mainline_pull_request(github, subject.repository, subject.commit_sha)


def read_pull_request_by_number(github: GitHubReader, repository: str, number: int) -> MergedPullRequest | None:
    listed = read_github(
        github, f"/repos/{repository}/pulls/{number}", endpoint="/repos/{owner}/{repo}/pulls/{number}"
    ).json()
    if not (listed.get("merged_at") and listed.get("merge_commit_sha")):
        return None
    return merged_pull_request(listed)


def find_mainline_pull_request(github: GitHubReader, repository: str, commit_sha: str) -> MergedPullRequest | None:
    response = read_github(
        github,
        f"/repos/{repository}/commits/{commit_sha}/pulls",
        endpoint="/repos/{owner}/{repo}/commits/{sha}/pulls",
    )
    for listed in response.json():
        is_merge_into_mainline = (
            listed.get("merge_commit_sha") == commit_sha
            and listed.get("merged_at")
            and (listed.get("base") or {}).get("ref") == POSTHOG_MAINLINE
        )
        if is_merge_into_mainline:
            return merged_pull_request(listed)
    return None


def merged_pull_request(listed: dict) -> MergedPullRequest:
    return MergedPullRequest(
        number=listed["number"],
        title=listed["title"],
        url=listed["html_url"],
        merge_commit_sha=listed["merge_commit_sha"],
        is_trusted_author=listed.get("author_association") in TRUSTED_AUTHOR_ASSOCIATIONS,
    )


def read_commit_diff_by_path(github: GitHubReader, repository: str, commit_sha: str) -> dict[str, str]:
    response = read_github(
        github,
        f"/repos/{repository}/commits/{commit_sha}",
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
    response = github.api_request(
        "GET",
        f"/repos/{repository}/contents/.gitattributes",
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


def is_published_from_repository(github: GitHubReader, repository: str, commit_sha: str, page_path: str) -> bool:
    for extension in PUBLISHED_DOCS_EXTENSIONS:
        response = github.api_request(
            "GET",
            f"/repos/{repository}/contents/{PUBLISHED_DOCS_DIRECTORY}/{page_path.strip('/')}{extension}",
            endpoint="/repos/{owner}/{repo}/contents/{path}",
            params={"ref": commit_sha},
            priority=Priority.NORMAL,
        )
        if response.status_code == 200:
            return True
        if response.status_code != 404:
            response.raise_for_status()
    return False
