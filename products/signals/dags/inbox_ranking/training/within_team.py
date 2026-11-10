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

`team_interval` is a bootstrap interval for a paired macro delta. It resamples teams, because the
groups of one team share an inbox and are not independent reads.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from posthog.dataclasses import frozen

BOOTSTRAP_DRAWS = 1000
BOOTSTRAP_SEED = 0
INTERVAL_PERCENTILES = (2.5, 97.5)


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


def team_interval(
    experiment: Sequence[pd.DataFrame | None],
    other: Sequence[pd.DataFrame | None],
    group_teams: pd.Series,
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """A percentile interval for the macro within-group delta, resampling teams with replacement.

    `experiment` and `other` hold the `group_aucs` of each paired seed, and `group_teams` maps a group
    id to its team. A group that is a team maps to itself. Each group's delta is its AUC gap averaged
    over the paired seeds. A resample's macro delta is the mean over every group of the drawn teams, a
    team drawn twice counting twice, so it is the same statistic as the macro delta itself. Fewer than
    two teams give no interval.
    """
    per_seed = [
        e["u"] / e["pairs"] - o["u"] / o["pairs"]
        for e, o in zip(experiment, other)
        if e is not None and o is not None and not e.empty
    ]
    if not per_seed:
        return {"low": None, "high": None, "teams": 0, "draws": 0}
    per_group = pd.concat(per_seed, axis=1).mean(axis=1)
    per_team = (
        pd.DataFrame({"delta": per_group.to_numpy(), "team": group_teams.loc[per_group.index].to_numpy()})
        .groupby("team")["delta"]
        .agg(["sum", "size"])
    )
    teams = len(per_team)
    if teams < 2:
        return {"low": None, "high": None, "teams": teams, "draws": 0}
    weights = np.random.default_rng(seed).multinomial(teams, np.full(teams, 1 / teams), size=draws)
    macro = (weights @ per_team["sum"].to_numpy()) / (weights @ per_team["size"].to_numpy())
    low, high = np.percentile(macro, INTERVAL_PERCENTILES)
    return {"low": float(low), "high": float(high), "teams": teams, "draws": draws}
