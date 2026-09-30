"""Pull requests that need the person: direct review requests, and their own PRs that fail or can merge.

Uses the project's GitHub integration and the person's linked GitHub login. Each query is one
GitHub search call through the integration, which goes through the GitHub egress gate.
"""

from datetime import datetime

from posthog.models.integration import GitHubIntegration, Integration

from ...facade.enums import ItemGroup, ItemReason, ItemSource
from ..candidates import URGENCY_THIS_WEEK, URGENCY_TODAY, URGENCY_WHEN_FREE, Candidate, SourceContext
from .base import Source

_SUBGROUP = 2
_PER_QUERY = 5


def _search(github: GitHubIntegration, query: str) -> list[dict]:
    response = github.api_request(
        "GET", "/search/issues", endpoint="/search/issues", params={"q": query, "per_page": _PER_QUERY}
    )
    if response.status_code != 200:
        return []
    return [item for item in response.json().get("items") or [] if item.get("pull_request")]


def _repository(item: dict) -> str:
    return "/".join((item.get("repository_url") or "").rstrip("/").split("/")[-2:])


def _timestamp(value: str | None) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else 0.0


class GitHubSource(Source):
    name = "github"

    def collect(self, ctx: SourceContext) -> list[Candidate]:
        login = ctx.user.get_github_login()
        integration = Integration.objects.filter(team_id=ctx.team.id, kind="github").order_by("id").first()
        if not login or integration is None:
            return []
        github = GitHubIntegration(integration)
        organization = github.organization()
        scope = f"is:pr is:open org:{organization}"
        queries = [
            # `user-review-requested` matches only requests sent to the person, not to their teams.
            (f"{scope} user-review-requested:{login}", ItemReason.REVIEW_REQUESTED, "review requested", 0),
            (f"{scope} author:{login} status:failure", ItemReason.YOUR_PULL_REQUEST, "checks failing", 1),
            (f"{scope} author:{login} review:approved status:success", ItemReason.YOUR_PULL_REQUEST, "approved", 2),
        ]
        # Someone waits on a review, and a red build blocks the person's own work; an approved PR
        # only needs a merge. A draft of either kind blocks nobody, so it drops a tier.
        urgency_for_order = {0: URGENCY_TODAY, 1: URGENCY_TODAY, 2: URGENCY_THIS_WEEK}
        candidates: list[Candidate] = []
        seen: set[str] = set()
        for query, reason, state, order in queries:
            for item in _search(github, query):
                key = f"github_pr:{_repository(item)}#{item.get('number')}"
                if key in seen:
                    continue
                seen.add(key)
                created = _timestamp(item.get("created_at"))
                draft = bool(item.get("draft"))
                candidates.append(
                    Candidate(
                        key=key,
                        group=ItemGroup.OTHER,
                        source=ItemSource.GITHUB,
                        reason=reason,
                        title=str(item.get("title") or f"Pull request #{item.get('number')}"),
                        url=str(item.get("html_url") or ""),
                        urgency=min(urgency_for_order[order] + int(draft), URGENCY_WHEN_FREE),
                        # Review requests wait longest first; your own PRs show the newest first.
                        sort_key=(_SUBGROUP, order, created if order == 0 else -_timestamp(item.get("updated_at"))),
                        facts={
                            "number": item.get("number"),
                            "repository": _repository(item),
                            "state": state,
                            "days_open": max(int((ctx.now.timestamp() - created) // 86400), 0) if created else None,
                            "draft": draft,
                        },
                    )
                )
        return candidates
