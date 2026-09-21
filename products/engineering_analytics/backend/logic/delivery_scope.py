"""Which pull requests a delivery read covers: one author's, one GitHub team's, or one pull request.

Every delivery read (the summary figures and the pull request timelines) takes exactly one scope and
compares it with the repository. A scope never holds more than one author or team, so no delivery read
can put people side by side (SPEC §2). A team scope matches pull request authors through the
``team_members`` snapshot, the same author→team rule the DORA team filter uses.
"""

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import DeliveryScopeKind
from products.engineering_analytics.backend.logic._shared import _require_repo


@frozen
class DeliveryScope:
    kind: DeliveryScopeKind
    # Set for the AUTHOR kind only.
    author: str | None = None
    # Set for the GITHUB_TEAM kind only.
    github_team: str | None = None
    # Set for the PULL_REQUEST kind only.
    pr_number: int | None = None
    repo_owner: str | None = None
    repo_name: str | None = None

    @classmethod
    def from_params(
        cls, *, author: str | None, github_team: str | None, pr_number: int | None, repo: str | None
    ) -> "DeliveryScope":
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
        """The scope as one string: the author login, the team slug, or 'owner/name#number'."""
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

    def pr_predicate(self, *, members_source: str | None, prefix: str = "pr.") -> str:
        """A SQL predicate over curated pull request columns (``prefix`` qualifies them) that is true for
        the pull requests in scope. A team scope without membership data matches nothing, so a team
        figure is never silently the whole repository."""
        if self.kind == DeliveryScopeKind.AUTHOR:
            return f"{prefix}author_handle = {{scope_author}}"
        if self.kind == DeliveryScopeKind.GITHUB_TEAM:
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
