"""AUC inside one team, for the inbox order.

The inbox sorts one team's reports, while a pooled AUC compares every report with every other.
A pooled AUC therefore rewards a model that knows which teams engage a lot, and that knowledge does
not change the order inside any inbox. A score equal to each team's past label rate gets a pooled
AUC well above 0.5 and a within-team AUC of exactly 0.5.

Only the pairs inside one team count here. `auc` weighs each team by its positive x negative pairs,
so it answers "how often does a positive report outrank a negative one in its own inbox". `macro`
weighs each team the same, so a few large teams cannot carry it.

`within_group_auc` is the same read over any grouping. The pair lane (`nn/pair_grade.py`) groups by
user, because a personal score asks whether it ranks one person's reports better.
"""

import numpy as np
import pandas as pd

from posthog.dataclasses import frozen


@frozen
class WithinTeamAuc:
    # None when no team has both outcome classes, like the pooled AUC helpers.
    auc: float | None = None
    macro: float | None = None
    # The teams with both outcome classes, and their summed positive x negative pairs.
    teams: int = 0
    pairs: int = 0

    def as_dict(self, prefix: str = "") -> dict[str, int | float | None]:
        return {
            f"{prefix}within_team_auc": self.auc,
            f"{prefix}within_team_auc_macro": self.macro,
            f"{prefix}within_team_teams": self.teams,
            f"{prefix}within_team_pairs": self.pairs,
        }


NO_TEAMS = WithinTeamAuc()


@frozen
class WithinGroupAuc:
    # None when no group has both outcome classes.
    auc: float | None = None
    macro: float | None = None
    # The groups with both outcome classes, and their summed positive x negative pairs.
    groups: int = 0
    pairs: int = 0


NO_GROUPS = WithinGroupAuc()


def group_aucs(outcomes: np.ndarray, scores: np.ndarray, group_ids: np.ndarray) -> pd.DataFrame | None:
    """The Mann-Whitney U and the positive x negative pairs of each group with both outcome classes,
    indexed by group id, with ties paid 0.5.

    A row without a group id is left out. A non-finite score makes the order undefined, so the
    result is None, which is what the pooled AUC reports for the same rows.
    """
    rows = pd.DataFrame(
        {
            "group": pd.Series(group_ids, dtype=object),
            "outcome": np.asarray(outcomes, dtype=bool),
            "score": np.asarray(scores, dtype=float),
        }
    )
    rows = rows.loc[rows["group"].notna()].copy()
    if not np.isfinite(rows["score"].to_numpy()).all():
        return None
    rank = rows.groupby("group")["score"].rank(method="average")
    rows["positive_rank"] = rank.where(rows["outcome"], 0.0)
    per_group = rows.groupby("group").agg(
        rows=("outcome", "size"),
        positives=("outcome", "sum"),
        positive_rank_sum=("positive_rank", "sum"),
    )
    per_group["negatives"] = per_group["rows"] - per_group["positives"]
    per_group = per_group[(per_group["positives"] > 0) & (per_group["negatives"] > 0)]
    return pd.DataFrame(
        {
            "u": per_group["positive_rank_sum"] - per_group["positives"] * (per_group["positives"] + 1) / 2,
            "pairs": per_group["positives"] * per_group["negatives"],
        }
    )


def summarize_groups(per_group: pd.DataFrame | None) -> WithinGroupAuc:
    """`auc` weighs each group by its pairs, and `macro` weighs each group the same."""
    if per_group is None or per_group.empty:
        return NO_GROUPS
    return WithinGroupAuc(
        auc=float(per_group["u"].sum() / per_group["pairs"].sum()),
        macro=float((per_group["u"] / per_group["pairs"]).mean()),
        groups=len(per_group),
        pairs=int(per_group["pairs"].sum()),
    )


def within_group_auc(outcomes: np.ndarray, scores: np.ndarray, group_ids: np.ndarray) -> WithinGroupAuc:
    """The Mann-Whitney U of each group, summed over the groups. A group with one outcome class has
    no pair and contributes nothing."""
    return summarize_groups(group_aucs(outcomes, scores, group_ids))


def within_team_auc(outcomes: np.ndarray, scores: np.ndarray, team_ids: np.ndarray) -> WithinTeamAuc:
    """`within_group_auc` over teams. A row without a team id is left out, and a non-finite score
    gives NO_TEAMS."""
    grade = within_group_auc(outcomes, scores, team_ids)
    if grade.auc is None:
        return NO_TEAMS
    return WithinTeamAuc(auc=grade.auc, macro=grade.macro, teams=grade.groups, pairs=grade.pairs)
