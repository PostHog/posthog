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
    # The issue's exception event as text, built the way `build_severity_state` builds severity's Jev input.
    state: str


class Tagger(Protocol):
    @property
    def source(self) -> ErrorTrackingIssueTag.Source: ...

    def applies(self, team_id: int) -> bool:
        """Whether this tagger may run for the team, for example behind its own flag or AI approval."""
        ...

    def answer(self, context: TagContext, definitions: Sequence[IssueTagDefinition]) -> dict[str, TagAnswer]:
        """Answer the given tags for the context's issue, keyed by tag key. Leave out a tag the tagger did not answer.

        All tags come in one call because the Jev tagger adds every tag question to the one decision request
        that severity inference sends, which holds at most `MAX_QUESTIONS_PER_REQUEST` questions.
        """
        ...
