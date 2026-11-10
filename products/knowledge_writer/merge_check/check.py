import httpx
from anthropic import Anthropic

from ..backend.facade.contracts import CriterionResult, MergeCheckReport
from ..backend.facade.enums import CriterionEffect, DocsChangeKind
from ..backend.settings import DocsSource
from .gates import rule_gates, with_existing_docs_pull_requests
from .gather import gather_merge
from .judge import JUDGE_MODEL, judge_merge
from .sources import GitHubReader, LandedChange, merged_pull_request, reached_default_branch, read_numbered_pull_request


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
    source: DocsSource | None,
    writer_login: str | None,
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
    if source is None:
        return no_docs_report(change, title=pull_request.title, reason="docs_source_unconfigured")
    evidence = gather_merge(change, listed, source=source, github=github, http=http, writer_login=writer_login)
    gates = rule_gates(evidence)
    if gates.blocking_reason is not None:
        return no_docs_report(
            change,
            title=pull_request.title,
            reason=gates.blocking_reason,
            criteria=gates.rows,
            low_confidence=gates.low_confidence,
        )
    page_url_by_key = {
        page.url.removeprefix(source.docs_url_prefix).strip("/"): page.url for page in evidence.editable_pages
    }
    verdict = judge_merge(
        anthropic_client,
        title=pull_request.title,
        judged_diff=evidence.judged_diff,
        docs_page_paths=list(page_url_by_key),
    )
    is_flagged_by_judge = verdict.needs_docs and verdict.change_kind is not None
    judge_row = CriterionResult(
        criterion="judge",
        value=str(verdict.change_kind) if is_flagged_by_judge else "no_docs",
        source=f"model:{JUDGE_MODEL}",
        evidence=verdict.reason,
        effect=CriterionEffect.SUPPORTS if is_flagged_by_judge else CriterionEffect.BLOCKS,
    )
    criteria = (*gates.rows, judge_row)
    if not is_flagged_by_judge:
        return no_docs_report(
            change,
            title=pull_request.title,
            reason=verdict.reason or "judge",
            criteria=criteria,
            low_confidence=gates.low_confidence,
        )
    named_page_keys = tuple(dict.fromkeys(path.strip("/") for path in verdict.page_urls))
    listed_page_urls = tuple(page_url_by_key[key] for key in named_page_keys if key in page_url_by_key)
    has_nothing_to_update = verdict.change_kind == DocsChangeKind.UPDATE and not listed_page_urls
    report = MergeCheckReport(
        commit_sha=commit_sha,
        commit_url=commit_url_for(change),
        title=pull_request.title,
        needs_docs=True,
        reason="judge",
        repository=change.repository,
        pull_request_number=change.pull_request_number,
        low_confidence=gates.low_confidence,
        criteria=criteria,
        change_kind=DocsChangeKind.CREATE if has_nothing_to_update else verdict.change_kind,
        page_urls=listed_page_urls,
        evidence=f"{pull_request.url}\n{verdict.reason}",
    )
    return with_existing_docs_pull_requests(report, evidence)


def commit_url_for(change: LandedChange) -> str:
    return f"https://github.com/{change.repository}/commit/{change.after}"


def no_docs_report(
    change: LandedChange,
    *,
    title: str,
    reason: str,
    criteria: tuple[CriterionResult, ...] = (),
    low_confidence: bool = False,
) -> MergeCheckReport:
    return MergeCheckReport(
        commit_sha=change.after,
        commit_url=commit_url_for(change),
        title=title,
        needs_docs=False,
        reason=reason,
        repository=change.repository,
        pull_request_number=change.pull_request_number,
        low_confidence=low_confidence,
        criteria=criteria or (gate_row(reason),),
    )


def gate_row(criterion: str) -> CriterionResult:
    return CriterionResult(
        criterion=criterion, value="true", source="rule_gate", evidence="", effect=CriterionEffect.BLOCKS
    )
