import re
from dataclasses import dataclass

import httpx

POSTHOG_REPOSITORY = "PostHog/posthog"
GITHUB_API_URL = "https://api.github.com"
SITEMAP_URL = "https://posthog.com/sitemap/sitemap-0.xml"
TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"MEMBER", "OWNER"})
SITEMAP_DOCS_URL_PATTERN = re.compile(r"<loc>(https://posthog\.com/docs/[^<]+)</loc>")
DIFF_FILE_HEADER_PATTERN = re.compile(r"^diff --git a/\S+ b/(\S+)$")
TEST_PATH_PATTERN = re.compile(
    r"(^|/)(tests?|__tests__|__snapshots__)/|(^|/)test_[^/]+\.py$|\.(test|spec|stories)\.[jt]sx?$"
)


@dataclass(frozen=True)
class MergedPullRequest:
    number: int
    title: str
    url: str
    is_trusted_author: bool


def github_client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=GITHUB_API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )


def find_merged_pull_request(github: httpx.Client, commit_sha: str) -> MergedPullRequest | None:
    response = github.get(f"/repos/{POSTHOG_REPOSITORY}/commits/{commit_sha}/pulls")
    response.raise_for_status()
    for listed in response.json():
        if listed.get("merge_commit_sha") != commit_sha:
            continue
        return MergedPullRequest(
            number=listed["number"],
            title=listed["title"],
            url=listed["html_url"],
            is_trusted_author=listed.get("author_association") in TRUSTED_AUTHOR_ASSOCIATIONS,
        )
    return None


def read_commit_diff_by_path(github: httpx.Client, commit_sha: str) -> dict[str, str]:
    response = github.get(
        f"/repos/{POSTHOG_REPOSITORY}/commits/{commit_sha}", headers={"Accept": "application/vnd.github.diff"}
    )
    response.raise_for_status()
    diff_by_path: dict[str, str] = {}
    current_path: str | None = None
    for line in response.text.splitlines(keepends=True):
        header = DIFF_FILE_HEADER_PATTERN.match(line.rstrip("\n"))
        if header:
            current_path = header.group(1)
            diff_by_path[current_path] = ""
        if current_path is not None:
            diff_by_path[current_path] += line
    return diff_by_path


def is_test_path(path: str) -> bool:
    return TEST_PATH_PATTERN.search(path) is not None


def read_docs_page_urls(http: httpx.Client) -> list[str]:
    response = http.get(SITEMAP_URL)
    response.raise_for_status()
    return SITEMAP_DOCS_URL_PATTERN.findall(response.text)
