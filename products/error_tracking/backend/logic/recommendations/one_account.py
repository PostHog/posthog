from datetime import timedelta
from typing import Any

from posthog.schema import ProductKey

from posthog.clickhouse.query_tagging import Feature, tag_queries

from .account_reach import AccountReach, account_lens_meta, account_names, fetch_account_reach, without_noise
from .impact_lens import MAX_ISSUES, ImpactLens, with_issue_details

MIN_SESSIONS = 20
MIN_TOP_ACCOUNT_SHARE = 0.5


def find_one_account(reach: AccountReach) -> dict[int, list[dict[str, Any]]]:
    """Pick the issues where one account causes most of the sessions: one customer's problem, not a general one."""
    result: dict[int, list[dict[str, Any]]] = {}
    for issue in reach.issues:
        if issue.sessions < MIN_SESSIONS or not issue.top_account or issue.top_account_share < MIN_TOP_ACCOUNT_SHARE:
            continue
        result.setdefault(issue.team_id, []).append(
            {
                "id": issue.issue_id,
                "people": issue.people,
                "sessions": issue.sessions,
                "accounts": issue.accounts,
                "top_account": {
                    "key": issue.top_account,
                    "name": None,
                    "session_share": round(issue.top_account_share, 4),
                },
            }
        )
    for team_id, issues in result.items():
        result[team_id] = sorted(issues, key=lambda i: -i["sessions"] * i["top_account"]["session_share"])[:MAX_ISSUES]
    return result


class OneAccountRecommendation(ImpactLens):
    type = "one_account"
    refresh_interval = timedelta(hours=6)
    # Shares its query with the other account lens, so both go stale together and the sweep runs it once.
    refresh_group = "account_reach"

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:one_account",
        )
        reach = without_noise(team_ids, fetch_account_reach(team_ids))
        found = find_one_account(reach)
        names = account_names(team_ids, [issue["top_account"]["key"] for issues in found.values() for issue in issues])
        for team_id, issues in found.items():
            for issue in issues:
                issue["top_account"]["name"] = names.get((team_id, issue["top_account"]["key"]))
        return account_lens_meta(team_ids, reach, with_issue_details(team_ids, found))
