from datetime import timedelta
from typing import Any

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.clickhouse.query_tagging import Feature, tag_queries

from .impact_lens import MAX_ISSUES, ImpactLens, with_issue_details
from .page_load import (
    RETURN_HOURS,
    Days,
    PageLoadRow,
    evaluable_teams,
    excluded_issues,
    fetch_page_load,
    find_repeated_findings,
)


def find_lost_visitors(rows: list[PageLoadRow], excluded: dict[int, set[str]]) -> dict[int, list[dict[str, Any]]]:
    """Pick the issues after which visitors leave the site and do not come back within a day, more often than visitors
    of the same kind on the same pages without errors, on both days."""
    return {
        team_id: [
            {
                "id": finding.issue_id,
                "pageviews": finding.measure.pageviews,
                "lost": finding.measure.observed,
                "rate": round(finding.measure.observed / finding.measure.pageviews, 4),
                "expected_rate": finding.expected_rate,
            }
            for finding in findings[:MAX_ISSUES]
        ]
        for team_id, findings in find_repeated_findings(rows, lambda row: row.lost, excluded).items()
    }


class LostVisitorRecommendation(ImpactLens):
    type = "lost_visitor"
    refresh_interval = timedelta(hours=6)
    # Shares its query with the other page load lens, so both go stale together and the sweep runs it once.
    refresh_group = "page_load"

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:lost_visitor",
        )
        days = Days.before(timezone.now())
        rows = fetch_page_load(team_ids, days)
        evaluable = evaluable_teams(rows, lambda row: row.lost)
        issues = with_issue_details(team_ids, find_lost_visitors(rows, excluded_issues(team_ids, days, rows)))
        return {
            team_id: {
                "days": [start.isoformat() for start in days.starts],
                "return_hours": RETURN_HOURS,
                "evaluable": team_id in evaluable,
                "issues": issues[team_id],
            }
            for team_id in team_ids
        }
