"""Orchestration for engineering_analytics.

Resolves caller inputs into the values the query layer needs and wraps the
result into contract types. The curated read layer (``backend/logic/views``) owns all
GitHub-shaped mapping and domain rules; this layer deals only in canonical types.
"""

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import PRLifecycle


def build_pr_lifecycle(*, team: Team, pr_number: int, repo: str | None) -> PRLifecycle | None:
    # Deferred: at module load this package is imported by core's Database.create_for
    # (via backend.logic.views). Importing the query layer here would pull
    # posthog.hogql.query -> Database while database.py is still initializing — a cycle.
    from products.engineering_analytics.backend.logic.queries.pr_lifecycle import query_pr_lifecycle  # noqa: PLC0415

    owner, name = _split_repo(repo)
    return query_pr_lifecycle(team=team, pr_number=pr_number, repo_owner=owner, repo_name=name)


def _split_repo(repo: str | None) -> tuple[str | None, str | None]:
    if not repo:
        return None, None
    owner, _, name = repo.partition("/")
    return owner or None, name or None
