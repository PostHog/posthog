from typing import Annotated, ClassVar, Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import Field
from pydantic.dataclasses import dataclass

from .enums import DocsChangeKind, DocsRequestSource

RawEvent = TypeVar("RawEvent", contravariant=True)

TASK_ORIGIN_KEY_MAX_LENGTH = 128

DedupeId = Annotated[
    str, Field(pattern=r"^knowledge_writer:[a-z_]+:[A-Za-z0-9._#-]+$", max_length=TASK_ORIGIN_KEY_MAX_LENGTH)
]


@dataclass(frozen=True, config={"extra": "forbid"})
class DocsRequest:
    source: DocsRequestSource
    source_url: str
    evidence: str
    change_kind: DocsChangeKind
    suggested_page_urls: Annotated[tuple[str, ...], Field(max_length=3)]
    trigger_instructions: str
    dedupe_id: DedupeId
    requested_by: str | None = None
    skip_judge: bool = False


@dataclass(frozen=True, config={"extra": "forbid"})
class AdapterVerdict:
    source: DocsRequestSource
    subject_id: str
    needs_docs: bool
    reason: str
    request: DocsRequest | None

    def __post_init__(self) -> None:
        if self.needs_docs != (self.request is not None):
            raise ValueError("request is set exactly when needs_docs")
        if self.request is not None and self.request.source != self.source:
            raise ValueError("request.source must match verdict.source")


class Adapter(Protocol[RawEvent]):
    source: ClassVar[DocsRequestSource]
    instructions: ClassVar[str]

    def assess(self, event: RawEvent) -> AdapterVerdict: ...


@dataclass(frozen=True, config={"extra": "forbid"})
class MergeCheckReport:
    commit_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    commit_url: str
    title: str
    needs_docs: bool
    reason: str
    change_kind: DocsChangeKind | None = None
    page_urls: Annotated[tuple[str, ...], Field(max_length=3)] = ()
    evidence: str = ""


@dataclass(frozen=True, config={"extra": "forbid"})
class DocsCommandRequest:
    repository: str
    pull_request_number: int
    pull_request_url: str
    head_sha: str
    note: str
    requested_by: str


IntakeStatus = Literal["no_docs", "unconfigured", "duplicate", "capped", "shadow", "joined", "started"]


@dataclass(frozen=True)
class IntakeOutcome:
    status: IntakeStatus
    task_id: UUID | None = None
    pull_request_url: str | None = None


class InvalidAdapterVerdict(ValueError):
    pass
