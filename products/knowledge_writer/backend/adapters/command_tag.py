import hashlib
from typing import ClassVar

from ..facade.contracts import AdapterVerdict, DocsCommandRequest, DocsRequest, MergeCheckReport
from ..facade.enums import DocsRequestSource


def command_subject_id(repository: str, pull_request_number: int) -> str:
    owner, name = repository.lower().split("/", 1)
    return f"{owner}.{name}#{pull_request_number}"


def command_dedupe_id(repository: str, pull_request_number: int) -> str:
    subject_id = command_subject_id(repository, pull_request_number)
    return f"knowledge_writer:{DocsRequestSource.COMMAND_TAG}:{hashlib.sha256(subject_id.encode()).hexdigest()}"


class CommandTagAdapter:
    source: ClassVar[DocsRequestSource] = DocsRequestSource.COMMAND_TAG
    instructions: ClassVar[str] = (
        "A PostHog teammate asked for this docs change with the docs command, and the merge check agreed. "
        "Read the linked pull request to learn what shipped, then change the docs pages it affects."
    )

    def assess(self, event: MergeCheckReport) -> AdapterVerdict:
        command = checked_command(event)
        subject_id = command_subject_id(command.repository, command.pull_request_number)
        if not event.needs_docs or event.change_kind is None:
            return AdapterVerdict(
                source=self.source,
                subject_id=subject_id,
                needs_docs=False,
                reason=event.reason,
                request=None,
                requested_by=command.requested_by,
                requested_by_user_id=command.requested_by_user_id,
            )
        return AdapterVerdict(
            source=self.source,
            subject_id=subject_id,
            needs_docs=True,
            reason=event.reason,
            request=DocsRequest(
                source=self.source,
                source_url=command.pull_request_url,
                evidence=f"Pull request {command.pull_request_url} at commit {command.head_sha}.\n{event.evidence}".strip(),
                change_kind=event.change_kind,
                suggested_page_urls=event.page_urls,
                trigger_instructions=command.note,
                dedupe_id=command_dedupe_id(command.repository, command.pull_request_number),
                requested_by=command.requested_by,
                requested_by_user_id=command.requested_by_user_id,
            ),
            requested_by=command.requested_by,
            requested_by_user_id=command.requested_by_user_id,
        )


def checked_command(event: MergeCheckReport) -> DocsCommandRequest:
    if event.command is None:
        raise ValueError("a docs command report carries its command")
    return event.command
