"""Author-scoped orchestration: one author's delivery summary and pull request timelines.

The author page compares one person's friction with the repository. It never ranks authors
against each other: every read takes exactly one author (SPEC §2).
"""

from products.engineering_analytics.backend.facade.contracts import AuthorPullRequestTimelines, AuthorSummary
from products.engineering_analytics.backend.logic._shared import _DEFAULT_WINDOW, _parse_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.author_summary import query_author_summary
from products.engineering_analytics.backend.logic.queries.author_timelines import query_author_timelines


def _require_author(author: str) -> str:
    handle = author.strip()
    if not handle:
        raise ValueError("author is required")
    return handle


def build_author_summary(
    *, curated: CuratedGitHubSource, author: str, date_from: str | None = None, date_to: str | None = None
) -> AuthorSummary:
    handle = _require_author(author)
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_author_summary(curated=curated, author=handle, date_from=parsed_from, date_to=parsed_to)


def build_author_timelines(
    *, curated: CuratedGitHubSource, author: str, date_from: str | None = None, date_to: str | None = None
) -> AuthorPullRequestTimelines:
    handle = _require_author(author)
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_author_timelines(curated=curated, author=handle, date_from=parsed_from, date_to=parsed_to)
