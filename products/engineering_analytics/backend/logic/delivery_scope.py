"""A team scope matches pull request authors through the ``team_members`` snapshot, the same
author-to-team rule the DORA team filter uses."""

from dataclasses import fields
from datetime import timedelta
from typing import Self

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import DeliveryScopeKind
from products.engineering_analytics.backend.logic._shared import _require_repo
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# How far before the window a merged PR's CI is still counted. A PR merged in the window usually
# ran its CI days before; older runs are left out so the runs and jobs scans stay bounded.
CI_LOOKBACK = timedelta(days=30)

_FIELDS_BY_KIND = {
    DeliveryScopeKind.AUTHOR: {"author"},
    DeliveryScopeKind.GITHUB_TEAM: {"github_team"},
    DeliveryScopeKind.PULL_REQUEST: {"pr_number", "repo_owner", "repo_name"},
}


@frozen
class DeliveryScope:
    kind: DeliveryScopeKind
    author: str | None = None
    github_team: str | None = None
    pr_number: int | None = None
    repo_owner: str | None = None
    repo_name: str | None = None

    def __post_init__(self) -> None:
        given = {field.name for field in fields(self) if field.name != "kind" and getattr(self, field.name) is not None}
        if given != _FIELDS_BY_KIND[self.kind]:
            raise ValueError(f"a {self.kind} scope sets exactly {', '.join(sorted(_FIELDS_BY_KIND[self.kind]))}")

    @classmethod
    def from_params(
        cls, *, author: str | None, github_team: str | None, pr_number: int | None, repo: str | None
    ) -> Self:
        """Build a scope from caller input; raises ValueError unless exactly one scope is given."""
        author = (author or "").strip() or None
        github_team = (github_team or "").strip() or None
        given = [value for value in (author, github_team, pr_number) if value is not None]
        if len(given) != 1:
            raise ValueError("pass exactly one of author, github_team or pr_number")
        if author is not None:
            return cls(kind=DeliveryScopeKind.AUTHOR, author=author)
        if github_team is not None:
            return cls(kind=DeliveryScopeKind.GITHUB_TEAM, github_team=github_team)
        owner, name = _require_repo(repo)
        return cls(kind=DeliveryScopeKind.PULL_REQUEST, pr_number=pr_number, repo_owner=owner, repo_name=name)

    @property
    def label(self) -> str:
        if self.kind == DeliveryScopeKind.AUTHOR:
            return self.author or ""
        if self.kind == DeliveryScopeKind.GITHUB_TEAM:
            return self.github_team or ""
        return f"{self.repo_owner}/{self.repo_name}#{self.pr_number}"

    def placeholders(self) -> dict[str, ast.Expr]:
        """The HogQL placeholders ``pr_predicate`` reads."""
        if self.kind == DeliveryScopeKind.AUTHOR:
            return {"scope_author": ast.Constant(value=self.author)}
        if self.kind == DeliveryScopeKind.GITHUB_TEAM:
            return {"scope_team": ast.Constant(value=self.github_team)}
        return {
            "scope_pr_number": ast.Constant(value=self.pr_number),
            "scope_repo_owner": ast.Constant(value=self.repo_owner),
            "scope_repo_name": ast.Constant(value=self.repo_name),
        }

    def pr_predicate(self, curated: CuratedGitHubSource, *, prefix: str = "pr.") -> str:
        """A SQL predicate over curated pull request columns (``prefix`` qualifies them) that is true for
        the pull requests in scope. A team scope without membership data matches nothing, so a team
        figure is never silently the whole repository."""
        if self.kind == DeliveryScopeKind.AUTHOR:
            return f"{prefix}author_handle = {{scope_author}}"
        if self.kind == DeliveryScopeKind.GITHUB_TEAM:
            members_source = curated.members_source()
            if members_source is None:
                return "0 = 1"
            return (
                f"{prefix}author_handle IN (SELECT member_handle FROM {members_source} AS scope_members "
                "WHERE scope_members.team_slug = {scope_team})"
            )
        return (
            f"{prefix}number = {{scope_pr_number}} AND {prefix}repo_owner = {{scope_repo_owner}} "
            f"AND {prefix}repo_name = {{scope_repo_name}}"
        )


@frozen
class SummaryScope(DeliveryScope):
    """A scope the delivery summary can read: one author or one GitHub team, never one pull request."""

    def __post_init__(self) -> None:
        DeliveryScope.__post_init__(self)
        if self.kind == DeliveryScopeKind.PULL_REQUEST:
            raise ValueError("the delivery summary takes an author or a github_team, not a single pull request")
