from dataclasses import dataclass

import httpx
from anthropic import Anthropic, APIError

from ..backend.facade.contracts import CriterionResult, MergeCheckReport
from ..backend.facade.enums import CriterionEffect
from ..backend.settings import DocsSource
from .facts import extract_facts, verify_quotes
from .gates import decide_with_rules, fact_gates, release_line_text, rule_gates, with_existing_docs_pull_requests
from .gather import DocsPage, MergeEvidence, gather_merge
from .judge import Decision, Variant, decide_with_judge
from .sources import (
    GitHubReader,
    LandedChange,
    MergedPullRequest,
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
    report_by_variant = merge_reports_by_variant(
        change,
        is_final_attempt=is_final_attempt,
        github=github,
        http=http,
        anthropic_client=anthropic_client,
        source=source,
        writer_login=writer_login,
        variants=(variant,),
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
) -> dict[Variant, MergeCheckReport]:
    commit_sha = change.after
    listed = read_numbered_pull_request(github, change)
    if not reached_default_branch(github, change.repository, listed, commit_sha):
        if not is_final_attempt:
            raise MergeNotOnDefaultBranch(commit_sha)
        return dict.fromkeys(
            variants, no_docs_report(change, title=listed.get("title") or "", reason="not_on_default_branch")
        )
    pull_request = merged_pull_request(listed, commit_sha)
    if pull_request is None and not is_final_attempt:
        raise MergeNotConfirmed(commit_sha)
    if pull_request is None:
        return dict.fromkeys(variants, no_docs_report(change, title="", reason="no_pull_request"))
    if source is None:
        return dict.fromkeys(
            variants, no_docs_report(change, title=pull_request.title, reason="docs_source_unconfigured")
        )
    evidence = gather_merge(change, listed, source=source, github=github, http=http, writer_login=writer_login)
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
        for key, page in page_by_key.items()
        if key in named_page_keys and page.source_path is not None
    }
    page_text_by_key = read_page_sources(github, source.docs_repository, source_path_by_key)
    gated = GatedMerge(
        change=change,
        pull_request=pull_request,
        evidence=evidence,
        gate_rows=gate_rows,
        low_confidence=low_confidence,
        page_by_key=page_by_key,
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
            )
            if variant == Variant.RULES
            else decide_with_judge(
                anthropic_client, evidence, docs_page_paths=docs_page_paths, page_text_by_key=page_text_by_key
            )
        )
        report_by_variant[variant] = decided_report(gated, decision)
    return report_by_variant


@dataclass(frozen=True)
class GatedMerge:
    change: LandedChange
    pull_request: MergedPullRequest
    evidence: MergeEvidence
    gate_rows: tuple[CriterionResult, ...]
    low_confidence: bool
    page_by_key: dict[str, DocsPage]


def decided_report(gated: GatedMerge, decision: Decision) -> MergeCheckReport:
    criteria = (*gated.gate_rows, *decision.rows)
    low_confidence = gated.low_confidence or decision.low_confidence
    title = gated.pull_request.title
    if not decision.needs_docs or decision.change_kind is None:
        return no_docs_report(
            gated.change, title=title, reason=decision.reason, criteria=criteria, low_confidence=low_confidence
        )
    report = MergeCheckReport(
        commit_sha=gated.change.after,
        commit_url=commit_url_for(gated.change),
        title=title,
        needs_docs=True,
        reason=decision.reason,
        repository=gated.change.repository,
        pull_request_number=gated.change.pull_request_number,
        low_confidence=low_confidence,
        criteria=criteria,
        change_kind=decision.change_kind,
        page_urls=tuple(gated.page_by_key[key].url for key in decision.page_keys if key in gated.page_by_key),
        evidence=f"{gated.pull_request.url}\n{decision.reason}",
    )
    return with_existing_docs_pull_requests(report, gated.evidence)


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
