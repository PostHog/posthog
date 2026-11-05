from typing import ClassVar, Protocol

from posthog.dataclasses import frozen

from products.error_tracking.backend.models import ErrorTrackingIssueTag


class TaggerConfig(Protocol):
    @property
    def source(self) -> ErrorTrackingIssueTag.Source: ...


@frozen
class JevTaggerConfig:
    source: ClassVar[ErrorTrackingIssueTag.Source] = ErrorTrackingIssueTag.Source.JEV

    instructions: str
    yes_at: float
    no_at: float

    def __post_init__(self) -> None:
        if not 0 <= self.no_at < self.yes_at <= 1:
            raise ValueError(f"expected 0 <= no_at < yes_at <= 1, got no_at={self.no_at} yes_at={self.yes_at}")


@frozen
class IssueTagDefinition:
    key: str
    label: str
    version: int
    enabled_flag: str
    # The taggers that may answer this tag, highest rank first. Manual is not listed because it always ranks first.
    taggers: tuple[TaggerConfig, ...]

    def sources_by_rank(self) -> tuple[ErrorTrackingIssueTag.Source, ...]:
        return (ErrorTrackingIssueTag.Source.MANUAL, *(tagger.source for tagger in self.taggers))


ISSUE_TAG_DEFINITIONS: tuple[IssueTagDefinition, ...] = ()


def get_issue_tag_definition(key: str) -> IssueTagDefinition:
    for definition in ISSUE_TAG_DEFINITIONS:
        if definition.key == key:
            return definition
    raise ValueError(f"unknown issue tag {key!r}")
