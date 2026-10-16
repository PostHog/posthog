from datetime import timedelta
from typing import Any

from posthog.schema import ProductKey

from posthog.clickhouse.query_tagging import Feature, tag_queries

from .account_reach import AccountReach, account_lens_meta, fetch_account_reach, without_noise
from .impact_lens import MAX_ISSUES, ImpactLens, with_issue_details

MIN_ACCOUNTS = 10
MIN_ACCOUNT_SHARE = 0.05


def find_many_accounts(reach: AccountReach) -> dict[int, list[dict[str, Any]]]:
    """Pick the issues that reached a large share of the team's active accounts."""
    result: dict[int, list[dict[str, Any]]] = {}
    for issue in reach.issues:
        active = reach.team(issue.team_id).active_accounts
        if issue.accounts < MIN_ACCOUNTS or active == 0 or issue.accounts / active < MIN_ACCOUNT_SHARE:
            continue
        result.setdefault(issue.team_id, []).append(
            {
                "id": issue.issue_id,
                "people": issue.people,
                "sessions": issue.sessions,
                "accounts": issue.accounts,
                "account_share": round(min(issue.accounts / active, 1.0), 4),
            }
        )
    for team_id, issues in result.items():
        result[team_id] = sorted(issues, key=lambda i: (-i["accounts"], -i["people"]))[:MAX_ISSUES]
    return result


class ManyAccountsRecommendation(ImpactLens):
    type = "many_accounts"
    refresh_interval = timedelta(hours=6)
    # Shares its query with the other account lens, so both go stale together and the sweep runs it once.
    refresh_group = "account_reach"

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:many_accounts",
        )
        reach = without_noise(team_ids, fetch_account_reach(team_ids))
        return account_lens_meta(team_ids, reach, with_issue_details(team_ids, find_many_accounts(reach)))
