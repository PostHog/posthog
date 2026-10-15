"""AUC inside one team, for the inbox order.

The inbox sorts one team's reports, while a pooled AUC compares every report with every other.
A pooled AUC therefore rewards a model that knows which teams engage a lot, and that knowledge does
not change the order inside any inbox. A score equal to each team's past label rate gets a pooled
AUC well above 0.5 and a within-team AUC of exactly 0.5.

Only the pairs inside one team count here. `auc` weighs each team by its positive x negative pairs,
so it answers "how often does a positive report outrank a negative one in its own inbox". `macro`
weighs each team the same, so a few large teams cannot carry it.
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


def within_team_auc(outcomes: np.ndarray, scores: np.ndarray, team_ids: np.ndarray) -> WithinTeamAuc:
    """The Mann-Whitney U of each team, with ties paid 0.5, summed over the teams.

    A row without a team id is left out. A team with one outcome class has no pair and contributes
    nothing. A non-finite score makes the order undefined, so the result is NO_TEAMS, which is what
    the pooled AUC reports for the same rows.
    """
    rows = pd.DataFrame(
        {
            "team": pd.Series(team_ids, dtype=object),
            "outcome": np.asarray(outcomes, dtype=bool),
            "score": np.asarray(scores, dtype=float),
        }
    )
    rows = rows.loc[rows["team"].notna()].copy()
    if rows.empty or not np.isfinite(rows["score"].to_numpy()).all():
        return NO_TEAMS
    rank = rows.groupby("team")["score"].rank(method="average")
    rows["positive_rank"] = rank.where(rows["outcome"], 0.0)
    per_team = rows.groupby("team").agg(
        rows=("outcome", "size"),
        positives=("outcome", "sum"),
        positive_rank_sum=("positive_rank", "sum"),
    )
    per_team["negatives"] = per_team["rows"] - per_team["positives"]
    per_team = per_team[(per_team["positives"] > 0) & (per_team["negatives"] > 0)]
    if per_team.empty:
        return NO_TEAMS
    pairs = per_team["positives"] * per_team["negatives"]
    u = per_team["positive_rank_sum"] - per_team["positives"] * (per_team["positives"] + 1) / 2
    return WithinTeamAuc(
        auc=float(u.sum() / pairs.sum()),
        macro=float((u / pairs).mean()),
        teams=len(per_team),
        pairs=int(pairs.sum()),
    )
