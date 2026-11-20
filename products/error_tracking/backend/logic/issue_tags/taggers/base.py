from collections.abc import Sequence
from typing import Protocol

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.error_tracking.backend.logic.issue_tags.registry import IssueTagDefinition
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueTag


@frozen
class TagAnswer:
    value: bool | None
    probability: float | None
    model: str | None
    question_version: int
    set_by: User | None

    def __post_init__(self) -> None:
        if self.probability is not None and not 0 <= self.probability <= 1:
            raise ValueError(f"probability must be between 0 and 1, got {self.probability}")


@frozen
class TagContext:
    issue: ErrorTrackingIssue
    event_properties: dict[str, object]


class Tagger(Protocol):
    @property
    def source(self) -> ErrorTrackingIssueTag.Source: ...

    def applies(self, team_id: int) -> bool:
        """Whether this tagger may run for the team, for example behind its own flag or AI approval."""
        ...

    def answer(self, context: TagContext, definitions: Sequence[IssueTagDefinition]) -> dict[str, TagAnswer]:
        """Return the given tags whose label applies to the context's issue, keyed by tag key, each with `value=True`.

        Do not return any other tag. This includes a tag that the tagger answered with no. A lower-ranked tagger
        cannot replace the row of this tagger, so a false row stops that tagger from applying the label.

        All tags come in one call so that a tagger can answer them together. The Jev tagger asks every tag question
        in one decision request, which holds at most `MAX_QUESTIONS_PER_REQUEST` questions.
        """
        ...
