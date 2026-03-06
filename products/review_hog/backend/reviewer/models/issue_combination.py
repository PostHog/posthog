from pydantic import BaseModel

from products.review_hog.backend.reviewer.models.issues_review import Issue


class IssueCombination(BaseModel):
    """Model for combining issues from all passes into a single list."""

    issues: list[Issue]
    """All issues found across all passes and chunks."""
