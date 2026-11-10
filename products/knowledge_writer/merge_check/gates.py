import dataclasses
from collections import Counter
from dataclasses import dataclass

from ..backend.facade.contracts import CriterionResult, MergeCheckReport
from ..backend.facade.enums import CriterionEffect, DocsChangeKind
from .facts import DOCS_DOC_IMPACTS, FACTS_MODEL, Audience, MergeFacts, ReleaseState
from .gather import MergeEvidence

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
    writer_docs_pull_requests = [
        pull_request.url for pull_request in evidence.docs_pull_requests if pull_request.is_opened_by_knowledge_writer
    ]
    other_docs_pull_requests = [
        pull_request.url
        for pull_request in evidence.docs_pull_requests
        if not pull_request.is_opened_by_knowledge_writer
    ]
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
            evidence=release_line_text(evidence),
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


def release_line_text(evidence: MergeEvidence) -> str:
    release_line = evidence.release_line
    if release_line is None:
        return "No GitHub releases."
    if release_line.newest_prerelease:
        return (
            f"Newest release {release_line.newest_prerelease} is a prerelease ahead of the latest stable "
            f"release {release_line.latest_stable or 'none'}, so this merge ships in the prerelease."
        )
    return f"Latest release {release_line.latest_stable} is stable."


def with_existing_docs_pull_requests(report: MergeCheckReport, evidence: MergeEvidence) -> MergeCheckReport:
    other_docs_pull_request_urls = tuple(
        pull_request.url
        for pull_request in evidence.docs_pull_requests
        if not pull_request.is_opened_by_knowledge_writer
    )
    if not report.needs_docs or not other_docs_pull_request_urls:
        return report
    return dataclasses.replace(
        report,
        change_kind=DocsChangeKind.REVIEW_EXISTING,
        evidence="\n".join([report.evidence, "Existing docs pull requests to review:", *other_docs_pull_request_urls]),
    )
