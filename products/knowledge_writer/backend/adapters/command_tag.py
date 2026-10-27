import hashlib
from typing import ClassVar

from ..facade.contracts import AdapterVerdict, DocsCommandRequest, DocsRequest
from ..facade.enums import DocsChangeKind, DocsRequestSource


class CommandTagAdapter:
    source: ClassVar[DocsRequestSource] = DocsRequestSource.COMMAND_TAG
    instructions: ClassVar[str] = (
        "A PostHog teammate asked for this docs change with the docs command, so the change is wanted. "
        "Read the linked pull request to learn what shipped, then change the docs pages it affects."
    )

    def assess(self, event: DocsCommandRequest) -> AdapterVerdict:
        owner, name = event.repository.lower().split("/", 1)
        subject_id = f"{owner}.{name}#{event.pull_request_number}"
        return AdapterVerdict(
            source=self.source,
            subject_id=subject_id,
            needs_docs=True,
            reason="requested",
            request=DocsRequest(
                source=self.source,
                source_url=event.pull_request_url,
                evidence=f"Pull request {event.pull_request_url} at commit {event.head_sha}.",
                change_kind=DocsChangeKind.UPDATE,
                suggested_page_urls=(),
                trigger_instructions=event.note,
                dedupe_id=f"knowledge_writer:{self.source}:{hashlib.sha256(subject_id.encode()).hexdigest()}",
                requested_by=event.requested_by,
                skip_judge=True,
            ),
        )
