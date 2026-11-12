import re
import gzip
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx
import requests

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority

from ..backend.logic.pull_requests import MAX_PULL_REQUEST_PAGES, PULL_REQUESTS_PER_PAGE, writer_pull_request
from ..backend.settings import DocsSource
from .sources import (
    GitHubReader,
    LandedChange,
    UnexpectedGitHubResponse,
    is_generated_path,
    is_test_path,
    read_diff_by_path,
    read_generated_path_patterns,
    read_github,
    read_github_or_none,
)

DOCS_SOURCE_EXTENSIONS = (".md", ".mdx")
INDEX_FILE_STEMS = frozenset({"index", "readme"})
PARTIAL_SEGMENT_PREFIX = "_"
ROUTE_GROUP_SEGMENT_PATTERN = re.compile(r"^\(.*\)$")
VERSION_SEGMENT_PATTERN = re.compile(r"^v?(\d+)(\.\d+)*$")
SITEMAP_LOCATION_PATTERN = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
MAX_CHILD_SITEMAPS = 50
DOCS_PULL_REQUEST_LOOKBACK = timedelta(days=14)
MAX_REFERENCE_READS = 10
MAX_RELEASES = 30
RELEASES_PER_PAGE = 100
MAX_RELEASE_PAGES = 20
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
    key: str
    source_path: str | None
    version: int | None


@dataclass(frozen=True)
class DocsPullRequest:
    url: str
    is_opened_by_knowledge_writer: bool


@dataclass
class DocsPullRequestScan:
    github: GitHubReader
    is_final_attempt: bool
    reference_reads_left: int = MAX_REFERENCE_READS
    was_shed: bool = False
    is_partial: bool = False

    def read(self, path: str, *, endpoint: str, params: dict[str, str | int]) -> requests.Response | None:
        if self.was_shed:
            return None
        try:
            return read_github(self.github, path, endpoint=endpoint, params=params, priority=Priority.BATCH)
        except (GitHubEgressBudgetExhausted, GitHubRateLimitError):
            if not self.is_final_attempt:
                raise
            self.was_shed = True
            self.is_partial = True
            return None

    def read_reference(self, path: str, *, endpoint: str, params: dict[str, str | int]) -> requests.Response | None:
        if self.reference_reads_left == 0:
            self.is_partial = True
            return None
        self.reference_reads_left -= 1
        return self.read(path, endpoint=endpoint, params=params)


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
    docs_commit_sha: str | None
    release_line: ReleaseLine | None
    docs_pull_requests: tuple[DocsPullRequest, ...]
    is_docs_pull_request_scan_partial: bool

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

    @property
    def page_by_key(self) -> dict[str, DocsPage]:
        return {page.key: page for page in self.editable_pages}

    @property
    def docs_page_paths(self) -> list[str]:
        return list(self.page_by_key)

    @property
    def writer_docs_pull_request_urls(self) -> list[str]:
        return [
            pull_request.url for pull_request in self.docs_pull_requests if pull_request.is_opened_by_knowledge_writer
        ]

    @property
    def other_docs_pull_request_urls(self) -> list[str]:
        return [
            pull_request.url
            for pull_request in self.docs_pull_requests
            if not pull_request.is_opened_by_knowledge_writer
        ]

    @property
    def release_text(self) -> str:
        release_line = self.release_line
        if release_line is None:
            return "No GitHub releases."
        if release_line.newest_prerelease:
            return (
                f"Newest release {release_line.newest_prerelease} is a prerelease ahead of the latest stable "
                f"release {release_line.latest_stable or 'none'}, so this merge ships in the prerelease."
            )
        return f"Latest release {release_line.latest_stable} is stable."


def gather_merge(
    change: LandedChange,
    listed: Mapping[str, Any],
    *,
    source: DocsSource,
    github: GitHubReader,
    http: httpx.Client,
    writer_login: str | None,
    is_final_attempt: bool,
    is_pinned_to_merge: bool = False,
) -> MergeEvidence:
    merged_at = parse_github_time(listed.get("merged_at"))
    docs_as_of = merged_at if is_pinned_to_merge else None
    diff_by_path = read_diff_by_path(github, change)
    generated_path_patterns = read_generated_path_patterns(github, change.repository, change.after)
    docs_commit_sha = read_docs_commit_sha(github, source.docs_repository, docs_as_of) if docs_as_of else None
    docs_tree_paths, is_docs_tree_truncated = read_docs_tree(github, source.docs_repository, docs_commit_sha or "HEAD")
    source_path_by_suffix = docs_source_path_by_suffix(docs_tree_paths)
    pages = [
        docs_page(url, source.docs_url_prefix, source_path_by_suffix)
        for url in read_sitemap_urls(http, source.sitemap_url)
        if url.startswith(source.docs_url_prefix)
    ]
    if docs_as_of is not None and not is_docs_tree_truncated:
        sitemap_pages = [page for page in pages if page.source_path is not None]
        pages = [*sitemap_pages, *merge_time_tree_pages(sitemap_pages, docs_tree_paths, source.docs_url_prefix)]
    docs_pull_requests, is_docs_pull_request_scan_partial = read_docs_pull_requests(
        github,
        source.docs_repository,
        change,
        merged_at=merged_at,
        docs_as_of=docs_as_of,
        docs_source_paths=frozenset(source_path_by_suffix.values()),
        writer_login=writer_login,
        is_final_attempt=is_final_attempt,
    )
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
        docs_commit_sha=docs_commit_sha,
        release_line=read_release_line(github, change.repository, published_by=docs_as_of),
        docs_pull_requests=docs_pull_requests,
        is_docs_pull_request_scan_partial=is_docs_pull_request_scan_partial,
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


def read_docs_commit_sha(github: GitHubReader, docs_repository: str, docs_as_of: datetime) -> str:
    response = read_github(
        github,
        f"/repos/{docs_repository}/commits",
        endpoint="/repos/{owner}/{repo}/commits",
        params={"until": docs_as_of.isoformat(), "per_page": 1},
    )
    commits = response.json()
    if not commits:
        raise UnexpectedGitHubResponse(f"{docs_repository} has no commit before {docs_as_of.isoformat()}")
    return commits[0]["sha"]


def read_docs_tree(github: GitHubReader, docs_repository: str, tree_ref: str) -> tuple[list[str], bool]:
    response = read_github(
        github,
        f"/repos/{docs_repository}/git/trees/{tree_ref}",
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
        segments = page_segments(path)
        for start in range(len(segments)):
            source_path_by_suffix.setdefault("/".join(segments[start:]), path)
    return source_path_by_suffix


def page_segments(source_path: str) -> list[str]:
    segments = [
        segment
        for segment in source_path.rsplit(".", 1)[0].split("/")
        if not ROUTE_GROUP_SEGMENT_PATTERN.match(segment)
    ]
    if segments and segments[-1].lower() in INDEX_FILE_STEMS:
        return segments[:-1]
    return segments


def merge_time_tree_pages(
    sitemap_pages: list[DocsPage], docs_tree_paths: list[str], docs_url_prefix: str
) -> list[DocsPage]:
    content_roots = Counter(
        content_root for page in sitemap_pages if (content_root := page_content_root(page)) is not None
    )
    if not content_roots:
        return []
    content_root = content_roots.most_common(1)[0][0]
    known_page_keys = {page.key for page in sitemap_pages}
    tree_pages: list[DocsPage] = []
    for path in docs_tree_paths:
        source_page_path = "/".join(page_segments(path))
        page_key = source_page_path.removeprefix(content_root)
        if not path.endswith(DOCS_SOURCE_EXTENSIONS) or not source_page_path.startswith(content_root):
            continue
        if any(segment.startswith(PARTIAL_SEGMENT_PREFIX) for segment in page_key.split("/")):
            continue
        if not page_key or page_key in known_page_keys:
            continue
        known_page_keys.add(page_key)
        version = major_version(page_key.split("/", 1)[0])
        tree_pages.append(DocsPage(url=f"{docs_url_prefix}{page_key}", key=page_key, source_path=path, version=version))
    return tree_pages


def page_content_root(page: DocsPage) -> str | None:
    if page.source_path is None or not page.key:
        return None
    source_page_path = "/".join(page_segments(page.source_path))
    if not source_page_path.endswith(f"/{page.key}"):
        return None
    return source_page_path.removesuffix(page.key)


def docs_page(url: str, docs_url_prefix: str, source_path_by_suffix: Mapping[str, str]) -> DocsPage:
    page_key = url.removeprefix(docs_url_prefix).strip("/")
    url_path = urlsplit(url).path.strip("/")
    first_segment = page_key.split("/", 1)[0]
    return DocsPage(
        url=url,
        key=page_key,
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


def read_release_line(github: GitHubReader, repository: str, *, published_by: datetime | None) -> ReleaseLine | None:
    releases = read_releases(github, repository, published_by=published_by)
    if releases is None:
        return None
    published = sorted(
        (
            release
            for release in releases
            if not release.get("draft") and happened_by(release.get("published_at"), published_by)
        ),
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


def read_releases(
    github: GitHubReader, repository: str, *, published_by: datetime | None
) -> list[dict[str, Any]] | None:
    path = f"/repos/{repository}/releases"
    endpoint = "/repos/{owner}/{repo}/releases"
    if published_by is None:
        response = read_github_or_none(github, path, endpoint=endpoint, params={"per_page": MAX_RELEASES})
        return None if response is None else response.json()
    releases: list[dict[str, Any]] = []
    for page in range(1, MAX_RELEASE_PAGES + 1):
        response = read_github_or_none(
            github, path, endpoint=endpoint, params={"per_page": RELEASES_PER_PAGE, "page": page}
        )
        if response is None:
            return None
        listed_page = response.json()
        releases.extend(listed_page)
        if len(listed_page) < RELEASES_PER_PAGE or has_stable_release_by(releases, published_by):
            return releases
    raise UnexpectedGitHubResponse(
        f"{repository} has no stable release before {published_by.isoformat()} in {MAX_RELEASE_PAGES} pages"
    )


def has_stable_release_by(releases: list[dict[str, Any]], published_by: datetime) -> bool:
    return any(
        not release.get("draft")
        and not release.get("prerelease")
        and happened_by(release.get("published_at"), published_by)
        for release in releases
    )


def read_docs_pull_requests(
    github: GitHubReader,
    docs_repository: str,
    change: LandedChange,
    *,
    merged_at: datetime | None,
    docs_as_of: datetime | None,
    docs_source_paths: frozenset[str],
    writer_login: str | None,
    is_final_attempt: bool,
) -> tuple[tuple[DocsPullRequest, ...], bool]:
    scan = DocsPullRequestScan(github, is_final_attempt=is_final_attempt)
    reference_pattern = merged_pull_request_reference_pattern(change)
    is_same_repository = docs_repository.lower() == change.repository.lower()
    oldest_update = merged_at - DOCS_PULL_REQUEST_LOOKBACK if merged_at else None
    found_by_url: dict[str, DocsPullRequest] = {}
    for listed in listed_pull_requests(scan, docs_repository, state="all", oldest_update=oldest_update):
        if docs_as_of is not None and not happened_by(listed.get("created_at"), docs_as_of):
            continue
        is_merged = happened_by(listed.get("merged_at"), docs_as_of)
        is_closed = listed.get("state") == "closed" and (
            docs_as_of is None or happened_by(listed.get("closed_at"), docs_as_of)
        )
        is_by_writer = writer_pull_request(listed, docs_repository, writer_login) is not None
        is_trusted = is_by_writer or is_merged or listed.get("author_association") in TRUSTED_AUTHOR_ASSOCIATIONS
        if is_closed and not is_merged:
            continue
        if not is_trusted:
            continue
        if is_same_repository and listed.get("number") == change.pull_request_number:
            continue
        if not reference_pattern.search(title_and_body(listed)):
            continue
        if is_same_repository and not changes_docs_sources(scan, docs_repository, listed["number"], docs_source_paths):
            continue
        found_by_url[listed["html_url"]] = DocsPullRequest(
            url=listed["html_url"], is_opened_by_knowledge_writer=is_by_writer
        )
    if writer_login is None:
        return tuple(found_by_url.values()), scan.is_partial
    for listed in listed_pull_requests(scan, docs_repository, state="open", oldest_update=None):
        if listed["html_url"] in found_by_url or writer_pull_request(listed, docs_repository, writer_login) is None:
            continue
        if docs_as_of is not None and not happened_by(listed.get("created_at"), docs_as_of):
            continue
        is_referenced = reference_pattern.search(title_and_body(listed)) or is_referenced_in_comments(
            scan, docs_repository, listed["number"], reference_pattern
        )
        if is_referenced:
            found_by_url[listed["html_url"]] = DocsPullRequest(
                url=listed["html_url"], is_opened_by_knowledge_writer=True
            )
    return tuple(found_by_url.values()), scan.is_partial


def title_and_body(listed: Mapping[str, Any]) -> str:
    return f"{listed.get('title') or ''}\n{listed.get('body') or ''}"


def is_referenced_in_comments(
    scan: DocsPullRequestScan, repository: str, pull_request_number: int, reference_pattern: re.Pattern[str]
) -> bool:
    response = scan.read_reference(
        f"/repos/{repository}/issues/{pull_request_number}/comments",
        endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
        params={"per_page": PULL_REQUESTS_PER_PAGE},
    )
    if response is None:
        return False
    return any(reference_pattern.search(comment.get("body") or "") for comment in response.json())


def merged_pull_request_reference_pattern(change: LandedChange) -> re.Pattern[str]:
    repository = re.escape(change.repository)
    number = change.pull_request_number
    return re.compile(rf"(github\.com/{repository}/pull/{number}|{repository}#{number})(?!\d)", re.IGNORECASE)


def listed_pull_requests(
    scan: DocsPullRequestScan, repository: str, *, state: str, oldest_update: datetime | None
) -> Iterator[dict[str, Any]]:
    for page in range(1, MAX_PULL_REQUEST_PAGES + 1):
        response = scan.read(
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
        if response is None:
            return
        listed_page = response.json()
        for listed in listed_page:
            updated_at = parse_github_time(listed.get("updated_at"))
            if oldest_update is not None and updated_at is not None and updated_at < oldest_update:
                return
            yield listed
        if len(listed_page) < PULL_REQUESTS_PER_PAGE:
            return
    scan.is_partial = True


def changes_docs_sources(
    scan: DocsPullRequestScan, repository: str, pull_request_number: int, docs_source_paths: frozenset[str]
) -> bool:
    response = scan.read_reference(
        f"/repos/{repository}/pulls/{pull_request_number}/files",
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/files",
        params={"per_page": PULL_REQUESTS_PER_PAGE},
    )
    if response is None:
        return False
    return any(changed.get("filename") in docs_source_paths for changed in response.json())


def parse_github_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def happened_by(github_time: object, as_of: datetime | None) -> bool:
    happened_at = parse_github_time(github_time)
    if happened_at is None:
        return False
    return as_of is None or happened_at <= as_of
