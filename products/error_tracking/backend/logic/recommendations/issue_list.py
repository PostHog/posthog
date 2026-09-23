from typing import Any
from uuid import UUID

from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingIssue

from .base import Recommendation


class IssueListRecommendation(Recommendation):
    """A recommendation whose meta carries an `issues` list of `{id, name, description, status}`.

    Subclasses pick the issues in ClickHouse and call `issues_by_id` to hydrate them.
    """

    def issues_by_id(self, team_ids: list[int], issue_ids: list[UUID]) -> dict[UUID, ErrorTrackingIssue]:
        return {
            issue.id: issue
            # nosemgrep: idor-lookup-without-team (team_id__in scopes the lookup; background sweep, not user input)
            for issue in ErrorTrackingIssue.objects.filter(team_id__in=team_ids, id__in=issue_ids).only(
                "id", "name", "description", "status"
            )
        }

    def is_completed(self, meta: dict[str, Any]) -> bool:
        return not meta.get("issues")

    def enrich(self, team: Team, meta: dict[str, Any]) -> dict[str, Any]:
        """Replace each cached status with the live Postgres value, so a status change from
        the card shows at once instead of waiting for the next recompute."""
        issues = meta.get("issues") or []
        if not issues:
            return meta

        statuses = {
            str(row_id): row_status
            for row_id, row_status in ErrorTrackingIssue.objects.filter(
                team=team, id__in=[i["id"] for i in issues]
            ).values_list("id", "status")
        }
        return {
            **meta,
            "issues": [{**issue, "status": statuses.get(issue["id"], issue.get("status"))} for issue in issues],
        }
