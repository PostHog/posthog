from collections.abc import Callable

from anthropic import Anthropic

from ..backend.facade.contracts import MergeCheckReport
from ..backend.facade.enums import DocsChangeKind
from .judge import judge_merge
from .sources import (
    DOCS_URL_PREFIX,
    GitHubReader,
    MergeSubject,
    is_generated_path,
    is_published_from_repository,
    is_test_path,
    read_commit_diff_by_path,
    read_generated_path_patterns,
    read_merged_pull_request,
)


def run_merge_check(
    subject: MergeSubject,
    *,
    github: GitHubReader,
    find_docs_page_urls: Callable[[str], list[str]],
    anthropic_client: Anthropic,
) -> MergeCheckReport:
    pull_request = read_merged_pull_request(github, subject)
    if pull_request is None:
        return no_docs_report(subject, commit_sha=subject.commit_sha, title="", reason="no_pull_request")
    commit_sha = pull_request.merge_commit_sha
    if not pull_request.is_trusted_author:
        return no_docs_report(subject, commit_sha=commit_sha, title=pull_request.title, reason="untrusted_author")
    diff_by_path = read_commit_diff_by_path(github, subject.repository, commit_sha)
    generated_path_patterns = read_generated_path_patterns(github, subject.repository, commit_sha)
    judged_diff = "".join(
        chunk
        for path, chunk in diff_by_path.items()
        if not is_test_path(path) and not is_generated_path(path, generated_path_patterns)
    )
    verdict = judge_merge(anthropic_client, title=pull_request.title, note=subject.note, judged_diff=judged_diff)
    if not verdict.needs_docs or verdict.change_kind is None:
        return no_docs_report(
            subject, commit_sha=commit_sha, title=pull_request.title, reason=verdict.reason or "judge"
        )
    page_urls = tuple(
        dict.fromkeys(url for url in find_docs_page_urls(verdict.docs_query) if url.startswith(DOCS_URL_PREFIX))
    )
    page_paths = (url.removeprefix(DOCS_URL_PREFIX).strip("/") for url in page_urls)
    if any(is_published_from_repository(github, subject.repository, commit_sha, path) for path in page_paths):
        return no_docs_report(subject, commit_sha=commit_sha, title=pull_request.title, reason="docs_in_source_repo")
    has_nothing_to_update = verdict.change_kind == DocsChangeKind.UPDATE and not page_urls
    return MergeCheckReport(
        commit_sha=commit_sha,
        commit_url=commit_url(subject.repository, commit_sha),
        title=pull_request.title,
        needs_docs=True,
        reason="judge",
        change_kind=DocsChangeKind.CREATE if has_nothing_to_update else verdict.change_kind,
        page_urls=page_urls,
        evidence=f"{pull_request.url}\n{verdict.reason}",
        docs_query=verdict.docs_query,
    )


def commit_url(repository: str, commit_sha: str | None) -> str:
    return f"https://github.com/{repository}/commit/{commit_sha}" if commit_sha else f"https://github.com/{repository}"


def no_docs_report(subject: MergeSubject, *, commit_sha: str | None, title: str, reason: str) -> MergeCheckReport:
    return MergeCheckReport(
        commit_sha=commit_sha,
        commit_url=commit_url(subject.repository, commit_sha),
        title=title,
        needs_docs=False,
        reason=reason,
    )
