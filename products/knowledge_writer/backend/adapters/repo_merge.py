from typing import ClassVar

from ..facade.contracts import AdapterVerdict, DocsRequest, MergeCheckReport, VerdictTrace
from ..facade.enums import DocsRequestSource


class RepoMergeAdapter:
    source: ClassVar[DocsRequestSource] = DocsRequestSource.REPO_MERGE
    instructions: ClassVar[str] = (
        "A merge to a repository's default branch changed something the docs describe, as judged by the merge check. "
        "Read the merged commit to learn what shipped, then change the docs pages it affects."
    )

    def assess(self, event: MergeCheckReport) -> AdapterVerdict:
        trace = VerdictTrace(
            repository=event.repository,
            pull_request_number=event.pull_request_number,
            low_confidence=event.low_confidence,
            criteria=event.criteria,
        )
        if not event.needs_docs or event.change_kind is None:
            return AdapterVerdict(
                source=self.source,
                subject_id=event.commit_sha,
                needs_docs=False,
                reason=event.reason,
                request=None,
                trace=trace,
            )
        return AdapterVerdict(
            source=self.source,
            subject_id=event.commit_sha,
            needs_docs=True,
            reason=event.reason,
            trace=trace,
            request=DocsRequest(
                source=self.source,
                source_url=event.commit_url,
                evidence=f"{event.title}\n{event.evidence}".strip(),
                change_kind=event.change_kind,
                suggested_page_urls=event.page_urls,
                trigger_instructions="",
                dedupe_id=f"knowledge_writer:{self.source}:{event.commit_sha}",
            ),
        )
