import httpx
from anthropic import Anthropic, APIError

from ..backend.facade.contracts import CriterionResult, MergeCheckReport
from ..backend.settings import DocsSource
from .deadline import CheckDeadline
from .facts import MergeFacts, extract_facts, verify_quotes
from .gates import decide_with_rules, fact_gates, gate_row, rule_gates, with_existing_docs_pull_requests
from .gather import DocsPage, MergeEvidence, gather_merge
from .judge import Decision, Variant, decide_with_judge, single_line
from .sources import (
    GitHubReader,
    LandedChange,
    merged_pull_request,
    reached_default_branch,
    read_page_sources,
    read_pull_request,
)

NOT_ON_DEFAULT_BRANCH_REASON = "not_on_default_branch"
NO_PULL_REQUEST_REASON = "no_pull_request"
DOCS_SOURCE_UNCONFIGURED_REASON = "docs_source_unconfigured"
UNDECIDED_REASONS = frozenset({NOT_ON_DEFAULT_BRANCH_REASON, NO_PULL_REQUEST_REASON, DOCS_SOURCE_UNCONFIGURED_REASON})


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
    deadline: CheckDeadline | None = None,
) -> MergeCheckReport:
    report_by_variant = merge_reports_by_variant(
        change,
        is_final_attempt=is_final_attempt,
        github=github,
        http=http,
        anthropic_client=anthropic_client,
        source=source,
        writer_login=writer_login,
        variants=(variant,),
        deadline=deadline,
    )
    return report_by_variant[variant]


def merge_reports_by_variant(
    change: LandedChange,
    *,
    is_final_attempt: bool,
    github: GitHubReader,
    http: httpx.Client,
    anthropic_client: Anthropic,
    source: DocsSource | None,
    writer_login: str | None,
    variants: tuple[Variant, ...],
    is_pinned_to_merge: bool = False,
    deadline: CheckDeadline | None = None,
) -> dict[Variant, MergeCheckReport]:
    commit_sha = change.after
    listed = read_pull_request(github, change.repository, change.pull_request_number)
    if not reached_default_branch(github, change.repository, listed, commit_sha):
        if not is_final_attempt:
            raise MergeNotOnDefaultBranch(commit_sha)
        return dict.fromkeys(
            variants, no_docs_report(change, title=listed.get("title") or "", reason=NOT_ON_DEFAULT_BRANCH_REASON)
        )
    pull_request = merged_pull_request(listed, commit_sha)
    if pull_request is None and not is_final_attempt:
        raise MergeNotConfirmed(commit_sha)
    if pull_request is None:
        return dict.fromkeys(variants, no_docs_report(change, title="", reason=NO_PULL_REQUEST_REASON))
    if source is None:
        return dict.fromkeys(
            variants, no_docs_report(change, title=pull_request.title, reason=DOCS_SOURCE_UNCONFIGURED_REASON)
        )
    evidence = gather_merge(
        change,
        listed,
        source=source,
        github=github,
        http=http,
        writer_login=writer_login,
        is_final_attempt=is_final_attempt,
        is_pinned_to_merge=is_pinned_to_merge,
    )
    gates = rule_gates(evidence)
    if gates.blocking_reason is not None:
        gated_report = no_docs_report(
            change,
            title=pull_request.title,
            reason=gates.blocking_reason,
            criteria=gates.rows,
            low_confidence=gates.low_confidence,
        )
        return dict.fromkeys(variants, gated_report)
    try:
        extracted_facts = extract_facts(anthropic_client, evidence, deadline=deadline)
    except APIError:
        if not is_final_attempt:
            raise
        extracted_facts = None
    are_quotes_verified = True
    facts = extracted_facts
    if extracted_facts is not None:
        facts, has_dropped_quotes = verify_quotes(extracted_facts, evidence)
        are_quotes_verified = not has_dropped_quotes
    fact_gate = fact_gates(facts, are_quotes_verified=are_quotes_verified)
    gate_rows = (*gates.rows, *fact_gate.rows)
    low_confidence = gates.low_confidence or fact_gate.low_confidence
    if fact_gate.blocking_reason is not None:
        fact_gated_report = no_docs_report(
            change,
            title=pull_request.title,
            reason=fact_gate.blocking_reason,
            criteria=gate_rows,
            low_confidence=low_confidence,
        )
        return dict.fromkeys(variants, fact_gated_report)
    named_page_keys = [page.page_path for page in facts.changed_pages] if facts is not None else []
    source_path_by_key = {
        key: page.source_path
        for key, page in evidence.page_by_key.items()
        if key in named_page_keys and page.source_path is not None
    }
    page_text_by_key = read_page_sources(
        github, source.docs_repository, source_path_by_key, docs_commit_sha=evidence.docs_commit_sha
    )
    report_by_variant: dict[Variant, MergeCheckReport] = {}
    for variant in variants:
        decision = (
            decide_with_rules(
                anthropic_client,
                evidence,
                facts=facts,
                page_text_by_key=page_text_by_key,
                is_final_attempt=is_final_attempt,
                deadline=deadline,
            )
            if variant == Variant.RULES
            else decide_with_judge(anthropic_client, evidence, page_text_by_key=page_text_by_key, deadline=deadline)
        )
        report_by_variant[variant] = decided_report(
            evidence, decision, facts=facts, gate_rows=gate_rows, low_confidence=low_confidence
        )
    return report_by_variant


def decided_report(
    evidence: MergeEvidence,
    decision: Decision,
    *,
    facts: MergeFacts | None,
    gate_rows: tuple[CriterionResult, ...],
    low_confidence: bool,
) -> MergeCheckReport:
    change = evidence.change
    criteria = (*gate_rows, *decision.rows)
    is_low_confidence = low_confidence or decision.low_confidence
    if not decision.needs_docs or decision.change_kind is None:
        return no_docs_report(
            change, title=evidence.title, reason=decision.reason, criteria=criteria, low_confidence=is_low_confidence
        )
    page_by_key = evidence.page_by_key
    report = MergeCheckReport(
        commit_sha=change.after,
        commit_url=commit_url_for(change),
        title=evidence.title,
        needs_docs=True,
        reason=decision.reason,
        repository=change.repository,
        pull_request_number=change.pull_request_number,
        low_confidence=is_low_confidence,
        criteria=criteria,
        change_kind=decision.change_kind,
        page_urls=tuple(page_by_key[key].url for key in decision.page_keys if key in page_by_key),
        evidence="\n".join([evidence.url, *finding_lines(page_by_key, facts, decision)]),
    )
    return with_existing_docs_pull_requests(report, evidence)


def finding_lines(page_by_key: dict[str, DocsPage], facts: MergeFacts | None, decision: Decision) -> list[str]:
    changed_pages = facts.changed_pages if facts is not None else []
    page_lines = [
        f'- {page_by_key[page.page_path].url} ({page.change_kind}): "{single_line(page.quote)}"'
        for page in changed_pages
        if page.page_path in decision.page_keys and page.page_path in page_by_key
    ]
    sentence_lines = [f'- outdated: "{single_line(sentence)}"' for sentence in decision.verified_sentences]
    return [*page_lines, *sentence_lines]


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
