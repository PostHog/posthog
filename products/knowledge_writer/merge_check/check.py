import httpx
from anthropic import Anthropic

from ..backend.facade.contracts import CriterionResult, MergeCheckReport
from ..backend.facade.enums import CriterionEffect, DocsChangeKind
from .judge import JUDGE_MODEL, judge_merge
from .sources import (
    DOCS_URL_PREFIX,
    GitHubReader,
    LandedChange,
    is_generated_path,
    is_published_from_repository,
    is_test_path,
    merged_pull_request,
    reached_default_branch,
    read_diff_by_path,
    read_docs_page_urls,
    read_generated_path_patterns,
    read_numbered_pull_request,
)


class MergeNotConfirmed(Exception):
    pass


class MergeNotOnDefaultBranch(Exception):
    pass


def run_merge_check(
    change: LandedChange,
    *,
    is_final_attempt: bool,
    github: GitHubReader,
    http: httpx.Client,
    anthropic_client: Anthropic,
) -> MergeCheckReport:
    commit_sha = change.after
    listed = read_numbered_pull_request(github, change)
    if not reached_default_branch(github, change.repository, listed, commit_sha):
        if not is_final_attempt:
            raise MergeNotOnDefaultBranch(commit_sha)
        return no_docs_report(change, title=listed.get("title") or "", reason="not_on_default_branch")
    pull_request = merged_pull_request(listed, commit_sha)
    if pull_request is None and not is_final_attempt:
        raise MergeNotConfirmed(commit_sha)
    if pull_request is None:
        return no_docs_report(change, title="", reason="no_pull_request")
    if not pull_request.is_trusted_author:
        return no_docs_report(change, title=pull_request.title, reason="untrusted_author")
    diff_by_path = read_diff_by_path(github, change)
    page_url_by_path = {url.removeprefix(DOCS_URL_PREFIX): url for url in read_docs_page_urls(http)}
    generated_path_patterns = read_generated_path_patterns(github, change.repository, commit_sha)
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
    is_flagged_by_judge = verdict.needs_docs and verdict.change_kind is not None
    judge_row = CriterionResult(
        criterion="judge",
        value=str(verdict.change_kind) if is_flagged_by_judge else "no_docs",
        source=f"model:{JUDGE_MODEL}",
        evidence=verdict.reason,
        effect=CriterionEffect.SUPPORTS if is_flagged_by_judge else CriterionEffect.BLOCKS,
    )
    if not is_flagged_by_judge:
        return no_docs_report(change, title=pull_request.title, reason=verdict.reason or "judge", criteria=(judge_row,))
    named_page_paths = tuple(dict.fromkeys(path.strip("/") for path in verdict.page_urls))
    if any(is_published_from_repository(github, change.repository, commit_sha, path) for path in named_page_paths):
        return no_docs_report(
            change,
            title=pull_request.title,
            reason="docs_in_source_repo",
            criteria=(judge_row, gate_row("docs_in_source_repo")),
        )
    listed_page_urls = tuple(page_url_by_path[path] for path in named_page_paths if path in page_url_by_path)
    has_nothing_to_update = verdict.change_kind == DocsChangeKind.UPDATE and not listed_page_urls
    return MergeCheckReport(
        commit_sha=commit_sha,
        commit_url=commit_url_for(change),
        title=pull_request.title,
        needs_docs=True,
        reason="judge",
        repository=change.repository,
        pull_request_number=change.pull_request_number,
        criteria=(judge_row,),
        change_kind=DocsChangeKind.CREATE if has_nothing_to_update else verdict.change_kind,
        page_urls=listed_page_urls,
        evidence=f"{pull_request.url}\n{verdict.reason}",
    )


def commit_url_for(change: LandedChange) -> str:
    return f"https://github.com/{change.repository}/commit/{change.after}"


def no_docs_report(
    change: LandedChange, *, title: str, reason: str, criteria: tuple[CriterionResult, ...] = ()
) -> MergeCheckReport:
    return MergeCheckReport(
        commit_sha=change.after,
        commit_url=commit_url_for(change),
        title=title,
        needs_docs=False,
        reason=reason,
        repository=change.repository,
        pull_request_number=change.pull_request_number,
        criteria=criteria or (gate_row(reason),),
    )


def gate_row(criterion: str) -> CriterionResult:
    return CriterionResult(
        criterion=criterion, value="true", source="rule_gate", evidence="", effect=CriterionEffect.BLOCKS
    )
