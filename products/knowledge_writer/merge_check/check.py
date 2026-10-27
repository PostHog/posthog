import httpx
from anthropic import Anthropic

from ..backend.facade.contracts import MergeCheckReport
from .judge import MAX_DIFF_CHARACTERS, judge_merge
from .routing import load_path_map, mapped_sections, section_page_urls
from .sources import (
    POSTHOG_REPOSITORY,
    GitHubReader,
    find_merged_pull_request,
    is_test_path,
    read_commit_diff_by_path,
    read_docs_page_urls,
)

MAX_SUGGESTED_PAGES = 3


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
    sections = mapped_sections(diff_by_path, load_path_map())
    if not sections:
        return no_docs_report(commit_sha, commit_url, title=pull_request.title, reason="unmapped")
    docs_page_urls = read_docs_page_urls(http)
    candidate_page_urls = [url for section in sections for url in section_page_urls(section, docs_page_urls)]
    non_test_diff = "".join(chunk for path, chunk in diff_by_path.items() if not is_test_path(path))
    verdict = judge_merge(
        anthropic_client,
        title=pull_request.title,
        non_test_diff=non_test_diff[:MAX_DIFF_CHARACTERS],
        section_page_urls=candidate_page_urls,
    )
    if not verdict.needs_docs or verdict.change_kind is None:
        return no_docs_report(commit_sha, commit_url, title=pull_request.title, reason=verdict.reason or "judge")
    listed_page_urls = [url for url in verdict.page_urls if url in candidate_page_urls]
    return MergeCheckReport(
        commit_sha=commit_sha,
        commit_url=commit_url,
        title=pull_request.title,
        needs_docs=True,
        reason="judge",
        change_kind=verdict.change_kind,
        page_urls=tuple(listed_page_urls[:MAX_SUGGESTED_PAGES]),
        evidence=f"{pull_request.url}\n{verdict.reason}",
    )


def no_docs_report(commit_sha: str, commit_url: str, *, title: str, reason: str) -> MergeCheckReport:
    return MergeCheckReport(commit_sha=commit_sha, commit_url=commit_url, title=title, needs_docs=False, reason=reason)
