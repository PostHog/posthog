from typing import Any, ClassVar, Protocol, TypeVar
from uuid import UUID

from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.issue_tags.flag import JEV_ISSUE_TAGS_FLAG
from products.error_tracking.backend.models import ErrorTrackingIssueTag


class TaggerConfig(Protocol):
    @property
    def source(self) -> ErrorTrackingIssueTag.Source: ...


_Config = TypeVar("_Config")


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
class RuleTaggerConfig:
    source: ClassVar[ErrorTrackingIssueTag.Source] = ErrorTrackingIssueTag.Source.RULE

    rule_id: UUID
    bytecode: list[Any]


@frozen
class IssueTagDefinition:
    key: str
    label: str
    # The tooltip a person sees. The Jev instructions are a separate text, written for a model.
    description: str
    question_version: int
    enabled_flag: str
    # The taggers that may answer this tag, highest rank first. Manual is not listed because it always ranks first.
    taggers: tuple[TaggerConfig, ...]

    def sources_ranked_above(self, source: ErrorTrackingIssueTag.Source) -> tuple[ErrorTrackingIssueTag.Source, ...]:
        """The sources whose answers `source` cannot replace. A source this definition does not list ranks lowest."""
        sources_by_rank = (ErrorTrackingIssueTag.Source.MANUAL, *(tagger.source for tagger in self.taggers))
        if source not in sources_by_rank:
            raise ValueError(f"{source} does not answer the issue tag {self.key!r}")
        return sources_by_rank[: sources_by_rank.index(source)]

    def tagger_config(self, config_type: type[_Config]) -> _Config:
        for tagger in self.taggers:
            if isinstance(tagger, config_type):
                return tagger
        raise ValueError(f"the issue tag {self.key!r} has no {config_type.__name__}")


ISSUE_TAG_DEFINITIONS: tuple[IssueTagDefinition, ...] = (
    IssueTagDefinition(
        key="cause_in_trace",
        label="Cause in trace",
        description="The stack trace shows where in your code the error starts.",
        question_version=1,
        enabled_flag=JEV_ISSUE_TAGS_FLAG,
        taggers=(
            JevTaggerConfig(
                instructions=(
                    "Does the stack trace point at the application's own code clearly enough that a developer "
                    "could fix it without reproducing the error?"
                ),
                yes_at=0.7,
                no_at=0.3,
            ),
        ),
    ),
)
