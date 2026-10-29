from typing import ClassVar

from ..facade.contracts import AdapterVerdict, DocsRequest, MergeCheckReport
from ..facade.enums import DocsRequestSource


class RepoMergeAdapter:
    source: ClassVar[DocsRequestSource] = DocsRequestSource.REPO_MERGE
    instructions: ClassVar[str] = (
        "A merge to PostHog/posthog master changed something the docs describe, as judged by the merge check. "
        "Read the merged commit to learn what shipped, then change the docs pages it affects."
    )

    def assess(self, event: MergeCheckReport) -> AdapterVerdict:
        subject_id = event.commit_sha or event.commit_url
        if not event.needs_docs or event.change_kind is None:
            return AdapterVerdict(
                source=self.source,
                subject_id=subject_id,
                needs_docs=False,
                reason=event.reason,
                request=None,
            )
        return AdapterVerdict(
            source=self.source,
            subject_id=subject_id,
            needs_docs=True,
            reason=event.reason,
            request=DocsRequest(
                source=self.source,
                source_url=event.commit_url,
                evidence=f"{event.title}\n{event.evidence}".strip(),
                change_kind=event.change_kind,
                suggested_page_urls=event.page_urls,
                trigger_instructions="",
                dedupe_id=f"knowledge_writer:{self.source}:{subject_id}",
            ),
        )
