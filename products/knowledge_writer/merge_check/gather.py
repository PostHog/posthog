import re
import gzip
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..backend.logic.pull_requests import MAX_PULL_REQUEST_PAGES, PULL_REQUESTS_PER_PAGE, writer_pull_request
from ..backend.settings import DocsSource
from .sources import (
    GitHubReader,
    LandedChange,
    is_generated_path,
    is_test_path,
    read_diff_by_path,
    read_generated_path_patterns,
    read_github,
)

DOCS_SOURCE_EXTENSIONS = (".md", ".mdx")
INDEX_FILE_STEMS = frozenset({"index", "readme"})
ROUTE_GROUP_SEGMENT_PATTERN = re.compile(r"^\(.*\)$")
VERSION_SEGMENT_PATTERN = re.compile(r"^v?(\d+)(\.\d+)*$")
SITEMAP_LOCATION_PATTERN = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
MAX_CHILD_SITEMAPS = 50
DOCS_PULL_REQUEST_LOOKBACK = timedelta(days=14)
MAX_RELEASES = 30
CI_PATH_PATTERN = re.compile(r"^(\.github|\.circleci|\.buildkite|\.gitlab|\.depot)/|(^|/)Dockerfile[^/]*$")
OWNERSHIP_PATH_PATTERN = re.compile(r"(^|/)(CODEOWNERS|OWNERS|owners\.ya?ml)$")
TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"MEMBER", "OWNER", "COLLABORATOR"})
GZIP_MAGIC_BYTES = b"\x1f\x8b"
LOCKFILE_NAMES = frozenset(
    {
        "bun.lockb",
        "Cargo.lock",
        "composer.lock",
        "Gemfile.lock",
        "go.sum",
        "package-lock.json",
        "Pipfile.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "uv.lock",
        "yarn.lock",
    }
)


class PathClass(StrEnum):
    CODE = "code"
    DOCS = "docs"
    TEST = "test"
    GENERATED = "generated"
    CI = "ci"
    LOCKFILE = "lockfile"
    OWNERSHIP = "ownership"


JUDGED_PATH_CLASSES = frozenset({PathClass.CODE, PathClass.DOCS, PathClass.CI})


@dataclass(frozen=True)
class DocsPage:
    url: str
    source_path: str | None
    version: int | None


@dataclass(frozen=True)
class DocsPullRequest:
    url: str
    author: str
    is_merged: bool
    is_opened_by_knowledge_writer: bool


@dataclass(frozen=True)
class ReleaseLine:
    latest_stable: str | None
    newest_prerelease: str | None

    @property
    def shipping_version(self) -> int | None:
        return major_version(self.newest_prerelease or self.latest_stable or "")


@dataclass(frozen=True)
class MergeEvidence:
    change: LandedChange
    title: str
    body: str
    url: str
    labels: tuple[str, ...]
    diff_by_path: Mapping[str, str]
    path_class_by_path: Mapping[str, PathClass]
    editable_pages: tuple[DocsPage, ...]
    not_editable_page_urls: tuple[str, ...]
    is_docs_tree_truncated: bool
    release_line: ReleaseLine | None
    docs_pull_requests: tuple[DocsPullRequest, ...]

    @property
    def judged_diff(self) -> str:
        return "".join(
            chunk for path, chunk in self.diff_by_path.items() if self.path_class_by_path[path] in JUDGED_PATH_CLASSES
        )

    @property
    def has_code_change(self) -> bool:
        return PathClass.CODE in self.path_class_by_path.values()

    @property
    def docs_versions(self) -> frozenset[int]:
        return frozenset(page.version for page in self.editable_pages if page.version is not None)


def gather_merge(
    change: LandedChange,
    listed: Mapping[str, Any],
    *,
    source: DocsSource,
    github: GitHubReader,
    http: httpx.Client,
    writer_login: str | None,
) -> MergeEvidence:
    diff_by_path = read_diff_by_path(github, change)
    generated_path_patterns = read_generated_path_patterns(github, change.repository, change.after)
    docs_tree_paths, is_docs_tree_truncated = read_docs_tree(github, source.docs_repository)
    source_path_by_suffix = docs_source_path_by_suffix(docs_tree_paths)
    pages = [
        docs_page(url, source.docs_url_prefix, source_path_by_suffix)
        for url in read_sitemap_urls(http, source.sitemap_url)
        if url.startswith(source.docs_url_prefix)
    ]
    return MergeEvidence(
        change=change,
        title=listed.get("title") or "",
        body=listed.get("body") or "",
        url=listed.get("html_url") or "",
        labels=tuple(str((label or {}).get("name", "")) for label in listed.get("labels") or []),
        diff_by_path=diff_by_path,
        path_class_by_path={path: classify_path(path, generated_path_patterns) for path in diff_by_path},
        editable_pages=tuple(page for page in pages if page.source_path is not None or is_docs_tree_truncated),
        not_editable_page_urls=tuple(
            page.url for page in pages if page.source_path is None and not is_docs_tree_truncated
        ),
        is_docs_tree_truncated=is_docs_tree_truncated,
        release_line=read_release_line(github, change.repository),
        docs_pull_requests=read_docs_pull_requests(
            github,
            source.docs_repository,
            change,
            merged_at=parse_github_time(listed.get("merged_at")),
            docs_source_paths=frozenset(source_path_by_suffix.values()),
            writer_login=writer_login,
        ),
    )


def classify_path(path: str, generated_path_patterns: list[str]) -> PathClass:
    file_name = path.rpartition("/")[2]
    if is_generated_path(path, generated_path_patterns):
        return PathClass.GENERATED
    if is_test_path(path):
        return PathClass.TEST
    if file_name in LOCKFILE_NAMES:
        return PathClass.LOCKFILE
    if OWNERSHIP_PATH_PATTERN.search(path):
        return PathClass.OWNERSHIP
    if CI_PATH_PATTERN.search(path):
        return PathClass.CI
    if path.endswith(DOCS_SOURCE_EXTENSIONS):
        return PathClass.DOCS
    return PathClass.CODE


def read_docs_tree(github: GitHubReader, docs_repository: str) -> tuple[list[str], bool]:
    response = read_github(
        github,
        f"/repos/{docs_repository}/git/trees/HEAD",
        endpoint="/repos/{owner}/{repo}/git/trees/{tree_sha}",
        params={"recursive": 1},
    )
    tree = response.json()
    paths = [entry["path"] for entry in tree.get("tree") or [] if entry.get("type") == "blob"]
    return paths, bool(tree.get("truncated"))


def docs_source_path_by_suffix(tree_paths: list[str]) -> dict[str, str]:
    source_path_by_suffix: dict[str, str] = {}
    for path in tree_paths:
        if not path.endswith(DOCS_SOURCE_EXTENSIONS):
            continue
        segments = [
            segment for segment in path.rsplit(".", 1)[0].split("/") if not ROUTE_GROUP_SEGMENT_PATTERN.match(segment)
        ]
        if segments and segments[-1].lower() in INDEX_FILE_STEMS:
            segments = segments[:-1]
        for start in range(len(segments)):
            source_path_by_suffix.setdefault("/".join(segments[start:]), path)
    return source_path_by_suffix


def docs_page(url: str, docs_url_prefix: str, source_path_by_suffix: Mapping[str, str]) -> DocsPage:
    page_key = url.removeprefix(docs_url_prefix).strip("/")
    url_path = urlsplit(url).path.strip("/")
    first_segment = page_key.split("/", 1)[0]
    return DocsPage(
        url=url,
        source_path=source_path_by_suffix.get(page_key) or source_path_by_suffix.get(url_path),
        version=major_version(first_segment),
    )


def major_version(name: str) -> int | None:
    matched = VERSION_SEGMENT_PATTERN.match(name.removeprefix("release-").split("-", 1)[0])
    return int(matched.group(1)) if matched else None


def read_sitemap_urls(http: httpx.Client, sitemap_url: str) -> list[str]:
    response = http.get(sitemap_url)
    response.raise_for_status()
    sitemap = sitemap_text(response)
    locations = SITEMAP_LOCATION_PATTERN.findall(sitemap)
    if "<sitemapindex" not in sitemap:
        return locations
    urls: list[str] = []
    for child_sitemap_url in locations[:MAX_CHILD_SITEMAPS]:
        child = http.get(child_sitemap_url)
        child.raise_for_status()
        urls.extend(SITEMAP_LOCATION_PATTERN.findall(sitemap_text(child)))
    return urls


def sitemap_text(response: httpx.Response) -> str:
    if response.content.startswith(GZIP_MAGIC_BYTES):
        return gzip.decompress(response.content).decode()
    return response.text


def read_release_line(github: GitHubReader, repository: str) -> ReleaseLine | None:
    response = github.api_request(
        "GET",
        f"/repos/{repository}/releases",
        endpoint="/repos/{owner}/{repo}/releases",
        params={"per_page": MAX_RELEASES},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    published = sorted(
        (release for release in response.json() if not release.get("draft") and release.get("published_at")),
        key=lambda release: release["published_at"],
        reverse=True,
    )
    if not published:
        return None
    latest_stable = next((release for release in published if not release.get("prerelease")), None)
    newest = published[0]
    is_prerelease_ahead = bool(newest.get("prerelease")) and newest is not latest_stable
    return ReleaseLine(
        latest_stable=latest_stable["tag_name"] if latest_stable else None,
        newest_prerelease=newest["tag_name"] if is_prerelease_ahead else None,
    )


def read_docs_pull_requests(
    github: GitHubReader,
    docs_repository: str,
    change: LandedChange,
    *,
    merged_at: datetime | None,
    docs_source_paths: frozenset[str],
    writer_login: str | None,
) -> tuple[DocsPullRequest, ...]:
    reference_pattern = merged_pull_request_reference_pattern(change)
    is_same_repository = docs_repository.lower() == change.repository.lower()
    oldest_update = merged_at - DOCS_PULL_REQUEST_LOOKBACK if merged_at else None
    found_by_url: dict[str, DocsPullRequest] = {}
    for listed in listed_pull_requests(github, docs_repository, state="all", oldest_update=oldest_update):
        is_merged = bool(listed.get("merged_at"))
        is_by_writer = writer_pull_request(listed, docs_repository, writer_login) is not None
        is_trusted = is_by_writer or is_merged or listed.get("author_association") in TRUSTED_AUTHOR_ASSOCIATIONS
        if listed.get("state") == "closed" and not is_merged:
            continue
        if not is_trusted:
            continue
        if is_same_repository and listed.get("number") == change.pull_request_number:
            continue
        if not reference_pattern.search(title_and_body(listed)):
            continue
        if is_same_repository and not changes_docs_sources(
            github, docs_repository, listed["number"], docs_source_paths
        ):
            continue
        found_by_url[listed["html_url"]] = docs_pull_request(listed, is_opened_by_knowledge_writer=is_by_writer)
    if writer_login is None:
        return tuple(found_by_url.values())
    for listed in listed_pull_requests(github, docs_repository, state="open", oldest_update=None):
        if listed["html_url"] in found_by_url or writer_pull_request(listed, docs_repository, writer_login) is None:
            continue
        is_referenced = reference_pattern.search(title_and_body(listed)) or is_referenced_in_comments(
            github, docs_repository, listed["number"], reference_pattern
        )
        if is_referenced:
            found_by_url[listed["html_url"]] = docs_pull_request(listed, is_opened_by_knowledge_writer=True)
    return tuple(found_by_url.values())


def docs_pull_request(listed: Mapping[str, Any], *, is_opened_by_knowledge_writer: bool) -> DocsPullRequest:
    return DocsPullRequest(
        url=listed["html_url"],
        author=str((listed.get("user") or {}).get("login", "")),
        is_merged=bool(listed.get("merged_at")),
        is_opened_by_knowledge_writer=is_opened_by_knowledge_writer,
    )


def title_and_body(listed: Mapping[str, Any]) -> str:
    return f"{listed.get('title') or ''}\n{listed.get('body') or ''}"


def is_referenced_in_comments(
    github: GitHubReader, repository: str, pull_request_number: int, reference_pattern: re.Pattern[str]
) -> bool:
    response = read_github(
        github,
        f"/repos/{repository}/issues/{pull_request_number}/comments",
        endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
        params={"per_page": PULL_REQUESTS_PER_PAGE},
    )
    return any(reference_pattern.search(comment.get("body") or "") for comment in response.json())


def merged_pull_request_reference_pattern(change: LandedChange) -> re.Pattern[str]:
    repository = re.escape(change.repository)
    number = change.pull_request_number
    return re.compile(rf"(github\.com/{repository}/pull/{number}|{repository}#{number})(?!\d)", re.IGNORECASE)


def listed_pull_requests(
    github: GitHubReader, repository: str, *, state: str, oldest_update: datetime | None
) -> Iterator[dict[str, Any]]:
    for page in range(1, MAX_PULL_REQUEST_PAGES + 1):
        response = read_github(
            github,
            f"/repos/{repository}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            params={
                "state": state,
                "sort": "updated",
                "direction": "desc",
                "per_page": PULL_REQUESTS_PER_PAGE,
                "page": page,
            },
        )
        listed_page = response.json()
        for listed in listed_page:
            updated_at = parse_github_time(listed.get("updated_at"))
            if oldest_update is not None and updated_at is not None and updated_at < oldest_update:
                return
            yield listed
        if len(listed_page) < PULL_REQUESTS_PER_PAGE:
            return


def changes_docs_sources(
    github: GitHubReader, repository: str, pull_request_number: int, docs_source_paths: frozenset[str]
) -> bool:
    response = read_github(
        github,
        f"/repos/{repository}/pulls/{pull_request_number}/files",
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/files",
        params={"per_page": PULL_REQUESTS_PER_PAGE},
    )
    return any(changed.get("filename") in docs_source_paths for changed in response.json())


def parse_github_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
