import dataclasses
from collections import Counter
from dataclasses import dataclass

from ..backend.facade.contracts import CriterionResult, MergeCheckReport
from ..backend.facade.enums import CriterionEffect, DocsChangeKind
from .gather import MergeEvidence

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
