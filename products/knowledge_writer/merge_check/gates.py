import dataclasses
from collections import Counter
from dataclasses import dataclass

from anthropic import Anthropic, APIError

from ..backend.facade.contracts import CriterionResult, MergeCheckReport
from ..backend.facade.enums import CriterionEffect, DocsChangeKind
from .deadline import CheckDeadline
from .facts import DOCS_DOC_IMPACTS, FACTS_MODEL, Audience, DocImpact, MergeFacts, ReleaseState, verified_page_findings
from .gather import MergeEvidence
from .judge import Decision

FACTS_SOURCE = f"model:{FACTS_MODEL}"
GATHER_SOURCE = "gather"
RULE_GATE_SOURCE = "rule_gate"
MAX_LISTED_PAGE_URLS = 5


@dataclass(frozen=True)
class GateResult:
    blocking_reason: str | None
    low_confidence: bool
    rows: tuple[CriterionResult, ...]


def rule_gates(evidence: MergeEvidence) -> GateResult:
    path_class_counts = Counter(evidence.path_class_by_path.values())
    writer_docs_pull_requests = evidence.writer_docs_pull_request_urls
    other_docs_pull_requests = evidence.other_docs_pull_request_urls
    shipping_version = evidence.release_line.shipping_version if evidence.release_line else None
    has_undocumented_version = (
        bool(evidence.docs_versions) and shipping_version is not None and shipping_version not in evidence.docs_versions
    )
    has_docs_pages = bool(evidence.editable_pages or evidence.not_editable_page_urls)
    rows = [
        CriterionResult(
            criterion="code_changed",
            value=str(evidence.has_code_change).lower(),
            source=RULE_GATE_SOURCE,
            evidence=", ".join(f"{path_class}: {count}" for path_class, count in sorted(path_class_counts.items())),
            effect=CriterionEffect.NEUTRAL if evidence.has_code_change else CriterionEffect.BLOCKS,
        ),
        CriterionResult(
            criterion="knowledge_writer_docs_pr",
            value=str(bool(writer_docs_pull_requests)).lower(),
            source=RULE_GATE_SOURCE,
            evidence="\n".join(writer_docs_pull_requests),
            effect=CriterionEffect.BLOCKS if writer_docs_pull_requests else CriterionEffect.NEUTRAL,
        ),
        CriterionResult(
            criterion="other_docs_pr",
            value=str(bool(other_docs_pull_requests)).lower(),
            source=GATHER_SOURCE,
            evidence="\n".join(other_docs_pull_requests),
            effect=CriterionEffect.NEUTRAL,
        ),
        CriterionResult(
            criterion="not_editable_here",
            value=str(len(evidence.not_editable_page_urls)),
            source=GATHER_SOURCE,
            evidence="\n".join(evidence.not_editable_page_urls[:MAX_LISTED_PAGE_URLS]),
            effect=CriterionEffect.NEUTRAL,
        ),
        CriterionResult(
            criterion="docs_version",
            value="undocumented" if has_undocumented_version else "documented",
            source=GATHER_SOURCE,
            evidence=evidence.release_text,
            effect=CriterionEffect.NEUTRAL,
        ),
    ]
    if evidence.labels:
        rows.append(
            CriterionResult(
                criterion="labels",
                value=", ".join(evidence.labels),
                source=GATHER_SOURCE,
                evidence="",
                effect=CriterionEffect.NEUTRAL,
            )
        )
    return GateResult(
        blocking_reason=first_blocking_criterion(rows),
        low_confidence=evidence.is_docs_tree_truncated or has_undocumented_version or not has_docs_pages,
        rows=tuple(rows),
    )


def fact_gates(facts: MergeFacts | None, *, are_quotes_verified: bool) -> GateResult:
    if facts is None:
        unavailable_row = CriterionResult(
            criterion="facts",
            value="unavailable",
            source=FACTS_SOURCE,
            evidence="The fact call returned no usable facts.",
            effect=CriterionEffect.NEUTRAL,
        )
        return GateResult(blocking_reason=None, low_confidence=True, rows=(unavailable_row,))
    release_state = facts.release_state
    is_flagged = release_state.value == ReleaseState.FLAGGED_OR_UNRELEASED
    is_flag_only_on_marker = is_flagged and release_state.rests_only_on_release_marker
    rows = [
        fact_row(
            "release_state", release_state.value, release_state.quote, blocks=is_flagged and not is_flag_only_on_marker
        ),
        fact_row(
            "audience", facts.audience.value, facts.audience.quote, blocks=facts.audience.value != Audience.CUSTOMER
        ),
        fact_row(
            "doc_impact",
            facts.doc_impact.value,
            facts.doc_impact.quote,
            blocks=facts.doc_impact.value not in DOCS_DOC_IMPACTS,
        ),
        fact_row(
            "generated_only",
            str(facts.generated_only.value).lower(),
            facts.generated_only.quote,
            blocks=facts.generated_only.value,
        ),
        fact_row(
            "no_public_page_fits",
            str(facts.no_public_page_fits.value).lower(),
            facts.no_public_page_fits.quote,
            blocks=facts.no_public_page_fits.value,
        ),
    ]
    return GateResult(
        blocking_reason=first_blocking_criterion(rows),
        low_confidence=is_flag_only_on_marker or not are_quotes_verified,
        rows=tuple(rows),
    )


def decide_with_rules(
    anthropic_client: Anthropic,
    evidence: MergeEvidence,
    *,
    facts: MergeFacts | None,
    page_text_by_key: dict[str, str],
    is_final_attempt: bool,
    deadline: CheckDeadline | None = None,
) -> Decision:
    if facts is None:
        return rules_decision(False, None, (), reason="facts_unavailable", low_confidence=True)
    is_removal = facts.doc_impact.value == DocImpact.REMOVED
    change_kind = DocsChangeKind.REMOVE if is_removal else DocsChangeKind.UPDATE
    named_page_keys = tuple(dict.fromkeys(page.page_path for page in facts.changed_pages))
    if not named_page_keys:
        if is_removal:
            return rules_decision(False, None, (), reason="removed_with_no_page")
        return rules_decision(True, DocsChangeKind.CREATE, (), reason="no_page_covers_change")
    readable_pages = {key: page_text_by_key[key] for key in named_page_keys if key in page_text_by_key}
    if not readable_pages:
        return rules_decision(True, change_kind, named_page_keys, reason="named_pages_unread", low_confidence=True)
    unread_page_keys = tuple(key for key in named_page_keys if key not in readable_pages)
    try:
        verified_findings = verified_page_findings(
            anthropic_client, evidence, page_text_by_key=readable_pages, deadline=deadline
        )
    except APIError:
        if not is_final_attempt:
            raise
        verified_findings = None
    if verified_findings is None:
        return rules_decision(True, change_kind, named_page_keys, reason="page_check_unavailable", low_confidence=True)
    page_check_row = CriterionResult(
        criterion="page_check",
        value=str(bool(verified_findings)).lower(),
        source=FACTS_SOURCE,
        evidence="\n".join(
            f"{finding.page_path}: {finding.outdated_sentence or finding.missing_detail}"
            for finding in verified_findings
        ),
        effect=CriterionEffect.SUPPORTS if verified_findings else CriterionEffect.BLOCKS,
    )
    if not verified_findings and unread_page_keys:
        return rules_decision(
            True,
            change_kind,
            unread_page_keys,
            reason="named_pages_unread",
            low_confidence=True,
            rows=(page_check_row,),
        )
    if not verified_findings:
        return rules_decision(False, None, (), reason="named_pages_still_accurate", rows=(page_check_row,))
    flagged_page_keys = tuple(dict.fromkeys(finding.page_path for finding in verified_findings))
    return rules_decision(
        True,
        change_kind,
        flagged_page_keys,
        reason="page_check",
        low_confidence=bool(unread_page_keys),
        rows=(page_check_row,),
    )


def rules_decision(
    needs_docs: bool,
    change_kind: DocsChangeKind | None,
    page_keys: tuple[str, ...],
    *,
    reason: str,
    low_confidence: bool = False,
    rows: tuple[CriterionResult, ...] = (),
) -> Decision:
    rule_row = CriterionResult(
        criterion="rules",
        value=str(change_kind) if needs_docs else "no_docs",
        source=RULE_GATE_SOURCE,
        evidence=reason,
        effect=CriterionEffect.SUPPORTS if needs_docs else CriterionEffect.BLOCKS,
    )
    return Decision(
        needs_docs=needs_docs,
        change_kind=change_kind,
        page_keys=page_keys,
        low_confidence=low_confidence,
        reason=reason,
        rows=(*rows, rule_row),
    )


def fact_row(criterion: str, value: str, quote: str, *, blocks: bool) -> CriterionResult:
    return CriterionResult(
        criterion=criterion,
        value=value,
        source=FACTS_SOURCE,
        evidence=quote,
        effect=CriterionEffect.BLOCKS if blocks else CriterionEffect.SUPPORTS,
    )


def first_blocking_criterion(rows: list[CriterionResult]) -> str | None:
    return next((row.criterion for row in rows if row.effect == CriterionEffect.BLOCKS), None)


def gate_row(criterion: str) -> CriterionResult:
    return CriterionResult(
        criterion=criterion, value="true", source=RULE_GATE_SOURCE, evidence="", effect=CriterionEffect.BLOCKS
    )


def with_existing_docs_pull_requests(report: MergeCheckReport, evidence: MergeEvidence) -> MergeCheckReport:
    other_docs_pull_request_urls = evidence.other_docs_pull_request_urls
    if not report.needs_docs or not other_docs_pull_request_urls:
        return report
    return dataclasses.replace(
        report,
        change_kind=DocsChangeKind.REVIEW_EXISTING,
        evidence="\n".join([report.evidence, "Existing docs pull requests to review:", *other_docs_pull_request_urls]),
    )
