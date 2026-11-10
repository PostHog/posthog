import httpx
from anthropic import Anthropic, APIError

from ..backend.facade.contracts import CriterionResult, MergeCheckReport
from ..backend.facade.enums import CriterionEffect
from ..backend.settings import DocsSource
from .facts import extract_facts, verify_quotes
from .gates import decide_with_rules, fact_gates, release_line_text, rule_gates, with_existing_docs_pull_requests
from .gather import gather_merge
from .judge import Variant, decide_with_judge
from .sources import (
    GitHubReader,
    LandedChange,
    merged_pull_request,
    reached_default_branch,
    read_numbered_pull_request,
    read_page_sources,
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
    source: DocsSource | None,
    writer_login: str | None,
    variant: Variant = Variant.JUDGE,
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
    page_by_key = {page.url.removeprefix(source.docs_url_prefix).strip("/"): page for page in evidence.editable_pages}
    docs_page_paths = list(page_by_key)
    release_text = release_line_text(evidence)
    try:
        extracted_facts = extract_facts(
            anthropic_client, evidence, release_text=release_text, docs_page_paths=docs_page_paths
        )
    except APIError:
        if not is_final_attempt:
            raise
        extracted_facts = None
    are_quotes_verified = True
    facts = extracted_facts
    if extracted_facts is not None:
        facts, has_dropped_quotes = verify_quotes(
            extracted_facts, evidence, release_text=release_text, docs_page_paths=docs_page_paths
        )
        are_quotes_verified = not has_dropped_quotes
    fact_gate = fact_gates(facts, are_quotes_verified=are_quotes_verified)
    gate_rows = (*gates.rows, *fact_gate.rows)
    low_confidence = gates.low_confidence or fact_gate.low_confidence
    if fact_gate.blocking_reason is not None:
        return no_docs_report(
            change,
            title=pull_request.title,
            reason=fact_gate.blocking_reason,
            criteria=gate_rows,
            low_confidence=low_confidence,
        )
    named_page_keys = [page.page_path for page in facts.changed_pages] if facts is not None else []
    source_path_by_key = {
        key: page.source_path
        for key, page in page_by_key.items()
        if key in named_page_keys and page.source_path is not None
    }
    page_text_by_key = read_page_sources(github, source.docs_repository, source_path_by_key)
    decision = (
        decide_with_rules(
            anthropic_client,
            evidence,
            facts=facts,
            page_text_by_key=page_text_by_key,
            is_final_attempt=is_final_attempt,
        )
        if variant == Variant.RULES
        else decide_with_judge(
            anthropic_client, evidence, docs_page_paths=docs_page_paths, page_text_by_key=page_text_by_key
        )
    )
    criteria = (*gate_rows, *decision.rows)
    low_confidence = low_confidence or decision.low_confidence
    if not decision.needs_docs or decision.change_kind is None:
        return no_docs_report(
            change, title=pull_request.title, reason=decision.reason, criteria=criteria, low_confidence=low_confidence
        )
    report = MergeCheckReport(
        commit_sha=commit_sha,
        commit_url=commit_url_for(change),
        title=pull_request.title,
        needs_docs=True,
        reason=decision.reason,
        repository=change.repository,
        pull_request_number=change.pull_request_number,
        low_confidence=low_confidence,
        criteria=criteria,
        change_kind=decision.change_kind,
        page_urls=tuple(page_by_key[key].url for key in decision.page_keys if key in page_by_key),
        evidence=f"{pull_request.url}\n{decision.reason}",
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
