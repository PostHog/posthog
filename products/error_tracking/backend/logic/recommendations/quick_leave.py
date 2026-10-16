from datetime import timedelta
from typing import Any

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.clickhouse.query_tagging import Feature, tag_queries

from .impact_lens import MAX_ISSUES, ImpactLens, with_issue_details
from .page_load import (
    MIN_PAGE_SECONDS,
    QUICK_LEAVE_SECONDS,
    RETURN_HOURS,
    Days,
    PageLoadRow,
    evaluable_teams,
    excluded_issues,
    fetch_page_load,
    find_repeated_findings,
    returned_rates,
)


def find_quick_leaves(rows: list[PageLoadRow], excluded: dict[int, set[str]]) -> dict[int, list[dict[str, Any]]]:
    """Pick the issues after which people leave the page sooner than people of the same kind on the same pages without
    errors, on both days. Such pages usually failed to load properly."""
    returned = returned_rates(rows)
    result: dict[int, list[dict[str, Any]]] = {}
    for team_id, findings in find_repeated_findings(rows, lambda row: row.quick, excluded).items():
        issues = []
        for finding in findings[:MAX_ISSUES]:
            returned_rate, expected_returned_rate = returned.get((team_id, finding.issue_id), (None, None))
            issues.append(
                {
                    "id": finding.issue_id,
                    "pageviews": finding.measure.pageviews,
                    "quick_leaves": finding.measure.observed,
                    "rate": round(finding.measure.observed / finding.measure.pageviews, 4),
                    "expected_rate": finding.expected_rate,
                    "returned_rate": returned_rate,
                    "expected_returned_rate": expected_returned_rate,
                }
            )
        result[team_id] = issues
    return result


class QuickLeaveRecommendation(ImpactLens):
    type = "quick_leave"
    refresh_interval = timedelta(hours=6)
    # Shares its query with the other page load lens, so both go stale together and the sweep runs it once.
    refresh_group = "page_load"

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:quick_leave",
        )
        days = Days.before(timezone.now())
        rows = fetch_page_load(team_ids, days)
        evaluable = evaluable_teams(rows, lambda row: row.quick)
        issues = with_issue_details(team_ids, find_quick_leaves(rows, excluded_issues(team_ids, days, rows)))
        return {
            team_id: {
                "days": [start.isoformat() for start in days.starts],
                # A quick leave is a page that lasted at least min_page_seconds and less than that plus quick_leave_seconds.
                "min_page_seconds": MIN_PAGE_SECONDS,
                "quick_leave_seconds": QUICK_LEAVE_SECONDS,
                "return_hours": RETURN_HOURS,
                "evaluable": team_id in evaluable,
                "issues": issues[team_id],
            }
            for team_id in team_ids
        }
