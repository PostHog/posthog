import httpx
from anthropic import Anthropic

from ..backend.facade.contracts import MergeCheckReport
from ..backend.facade.enums import DocsChangeKind
from .judge import judge_merge
from .sources import (
    DOCS_URL_PREFIX,
    POSTHOG_REPOSITORY,
    GitHubReader,
    find_merged_pull_request,
    is_generated_path,
    is_test_path,
    read_commit_diff_by_path,
    read_docs_page_urls,
    read_generated_path_patterns,
)


def run_merge_check(
    commit_sha: str,
    *,
    github: GitHubReader,
    http: httpx.Client,
    anthropic_client: Anthropic,
) -> MergeCheckReport:
    commit_url = f"https://github.com/{POSTHOG_REPOSITORY}/commit/{commit_sha}"
    pull_request = find_merged_pull_request(github, commit_sha)
    if pull_request is None:
        return no_docs_report(commit_sha, commit_url, title="", reason="no_pull_request")
    if not pull_request.is_trusted_author:
        return no_docs_report(commit_sha, commit_url, title=pull_request.title, reason="untrusted_author")
    diff_by_path = read_commit_diff_by_path(github, commit_sha)
    page_url_by_path = {url.removeprefix(DOCS_URL_PREFIX): url for url in read_docs_page_urls(http)}
    generated_path_patterns = read_generated_path_patterns(github, commit_sha)
    judged_diff = "".join(
        chunk
        for path, chunk in diff_by_path.items()
        if not is_test_path(path) and not is_generated_path(path, generated_path_patterns)
    )
    verdict = judge_merge(
        anthropic_client,
        title=pull_request.title,
        judged_diff=judged_diff,
        docs_page_paths=list(page_url_by_path),
    )
    if not verdict.needs_docs or verdict.change_kind is None:
        return no_docs_report(commit_sha, commit_url, title=pull_request.title, reason=verdict.reason or "judge")
    listed_page_urls = tuple(
        dict.fromkeys(page_url_by_path[path] for path in verdict.page_urls if path in page_url_by_path)
    )
    has_nothing_to_update = verdict.change_kind == DocsChangeKind.UPDATE and not listed_page_urls
    return MergeCheckReport(
        commit_sha=commit_sha,
        commit_url=commit_url,
        title=pull_request.title,
        needs_docs=True,
        reason="judge",
        change_kind=DocsChangeKind.CREATE if has_nothing_to_update else verdict.change_kind,
        page_urls=listed_page_urls,
        evidence=f"{pull_request.url}\n{verdict.reason}",
    )


def no_docs_report(commit_sha: str, commit_url: str, *, title: str, reason: str) -> MergeCheckReport:
    return MergeCheckReport(commit_sha=commit_sha, commit_url=commit_url, title=title, needs_docs=False, reason=reason)
