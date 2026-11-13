import hashlib
from typing import TYPE_CHECKING, ClassVar

from ..facade.contracts import AdapterVerdict, DocsRequest, MergeCheckReport, VerdictTrace
from ..facade.enums import DocsRequestSource

if TYPE_CHECKING:
    from ..temporal.merge_workflow import MergeCheckInputs


def pull_request_key(repository: str, pull_request_number: int | None) -> str:
    owner, name = repository.lower().split("/", 1)
    return f"{owner}.{name}#{pull_request_number}"


def pull_request_dedupe_id(repository: str, pull_request_number: int) -> str:
    digest = hashlib.sha256(pull_request_key(repository, pull_request_number).encode()).hexdigest()
    return f"knowledge_writer:pull_request:{digest}"


class RepoMergeAdapter:
    source: ClassVar[DocsRequestSource] = DocsRequestSource.REPO_MERGE
    instructions: ClassVar[str] = (
        "A merge to a repository's default branch changed something the docs describe, as judged by the docs check. "
        "Read the merged commit to learn what shipped, then change the docs pages it affects."
    )

    def assess(self, report: MergeCheckReport, inputs: "MergeCheckInputs") -> AdapterVerdict:
        source = inputs.origin
        subject_id = pull_request_dedupe_id(report.repository, report.pull_request_number)
        trace = VerdictTrace(
            repository=report.repository,
            pull_request_number=report.pull_request_number,
            low_confidence=report.low_confidence,
            criteria=report.criteria,
        )
        if not report.needs_docs or report.change_kind is None:
            return AdapterVerdict(
                source=source,
                subject_id=subject_id,
                needs_docs=False,
                reason=report.reason,
                request=None,
                trace=trace,
            )
        return AdapterVerdict(
            source=source,
            subject_id=subject_id,
            needs_docs=True,
            reason=report.reason,
            trace=trace,
            request=DocsRequest(
                source=source,
                source_url=report.commit_url,
                evidence=f"{report.title}\n{report.evidence}".strip(),
                change_kind=report.change_kind,
                suggested_page_urls=report.page_urls,
                trigger_instructions=inputs.note,
                dedupe_id=subject_id,
                requested_by=inputs.requested_by,
                requested_by_user_id=inputs.requested_by_user_id,
            ),
        )
