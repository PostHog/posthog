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


class Tagger(Protocol):
    @property
    def source(self) -> ErrorTrackingIssueTag.Source: ...

    def applies(self, team_id: int) -> bool:
        """Whether this tagger may run for the team, for example behind its own flag or AI approval."""
        ...

    def answer(self, issue: ErrorTrackingIssue, definitions: Sequence[IssueTagDefinition]) -> dict[str, TagAnswer]:
        """Answer the given tags for one issue, keyed by tag key. Leave out a tag the tagger did not answer.

        All tags come in one call so that a tagger can ask them together, as the Jev tagger must to share
        severity's request.
        """
        ...
