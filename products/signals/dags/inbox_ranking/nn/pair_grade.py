"""The pair lane's grade: a pair experiment against its pair baseline and its report-level
reference, within user, on the same holdout pairs.

A personal score is read inside one person's inbox, so a group here is one user in one team: the
reports that person sees in that project. The AUC is `within_group_auc` over those groups, as a
macro over users (each user with both outcome classes weighs the same, and a user with one class is
left out) and pooled over their pairs (each user weighs by its positive x negative pairs).

Every read is per head and per seed, for each arm, in two scopes: every user, and the users outside
the dogfood project, whose own inbox use is not a customer's. Inside each scope the holdout pairs
are also sliced by the user's prior views (`HISTORY_BUCKETS`) and by whether the user was a
suggested reviewer of the report. The deltas are the experiment minus the baseline and the
experiment minus the reference, over the paired seeds. The macro delta also gets a team bootstrap
interval: the users of one team share an inbox, so they are not independent reads.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from products.signals.dags.inbox_ranking.dataset.queries import LABELS_TEAM_ID
from products.signals.dags.inbox_ranking.multihead.prototype import ExampleTable
from products.signals.dags.inbox_ranking.nn.pairs import HISTORY_BUCKETS
from products.signals.dags.inbox_ranking.training.families import PAIR_GRAIN
from products.signals.dags.inbox_ranking.training.within_team import group_aucs, summarize_groups

# PostHog's own project, where the inbox's builders are its users.
DOGFOOD_TEAM_ID = LABELS_TEAM_ID
# Prior views from which a user counts as having history, read as one slice as well as the buckets.
WITH_HISTORY_MIN_VIEWS = 10
BOOTSTRAP_DRAWS = 1000
BOOTSTRAP_SEED = 0
INTERVAL_PERCENTILES = (2.5, 97.5)

ALL = "all"
NON_DOGFOOD = "non_dogfood"
EXPERIMENT_ARM = "experiment"
BASELINE_ARM = "baseline"
REFERENCE_ARM = "reference"
# The delta block name and the arm the experiment is compared with.
COMPARISONS = (("vs_baseline", BASELINE_ARM), ("vs_reference", REFERENCE_ARM))
READS = ("macro", "pooled")
_GROUP_COLUMNS = ["report_team_id", "user_distinct_id"]


def pair_scopes(rows: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        ALL: np.ones(len(rows), dtype=bool),
        NON_DOGFOOD: rows["report_team_id"].to_numpy() != DOGFOOD_TEAM_ID,
    }


def pair_slices(rows: pd.DataFrame) -> dict[str, np.ndarray]:
    prior_views = rows["prior_views"].to_numpy()
    suggested = rows["is_suggested_reviewer"].to_numpy(dtype=bool)
    slices = {ALL: np.ones(len(rows), dtype=bool)}
    for name, lowest, highest in HISTORY_BUCKETS:
        in_bucket = prior_views >= lowest
        if highest is not None:
            in_bucket &= prior_views <= highest
        slices[f"history_{name}"] = in_bucket
    slices[f"history_{WITH_HISTORY_MIN_VIEWS}_plus"] = prior_views >= WITH_HISTORY_MIN_VIEWS
    slices["suggested_reviewer"] = suggested
    slices["not_suggested_reviewer"] = ~suggested
    return slices


def _delta_summary(experiment: Sequence[float | None], other: Sequence[float | None]) -> dict[str, Any]:
    deltas = [e - o for e, o in zip(experiment, other) if e is not None and o is not None]
    return {
        "paired_seeds": len(deltas),
        "mean_delta_auc": float(np.mean(deltas)) if deltas else None,
        "min_delta_auc": min(deltas) if deltas else None,
        "max_delta_auc": max(deltas) if deltas else None,
        "wins": sum(1 for delta in deltas if delta > 0),
    }


def team_interval(
    experiment: Sequence[pd.DataFrame | None],
    other: Sequence[pd.DataFrame | None],
    group_teams: pd.Series,
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """A percentile interval for the macro within-user delta, resampling teams with replacement.

    Each user's delta is its AUC gap averaged over the paired seeds. A resample's macro delta is the
    mean over every user of the drawn teams, a team drawn twice counting twice, so it is the same
    statistic as the macro delta itself. Fewer than two teams give no interval.
    """
    per_seed = [
        e["u"] / e["pairs"] - o["u"] / o["pairs"]
        for e, o in zip(experiment, other)
        if e is not None and o is not None and not e.empty
    ]
    if not per_seed:
        return {"low": None, "high": None, "teams": 0, "draws": 0}
    per_user = pd.concat(per_seed, axis=1).mean(axis=1)
    per_team = (
        pd.DataFrame({"delta": per_user.to_numpy(), "team": group_teams.loc[per_user.index].to_numpy()})
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


def _slice_grade(
    outcomes: np.ndarray,
    groups: np.ndarray,
    group_teams: pd.Series,
    arms: Mapping[str, Sequence[np.ndarray] | None],
    draws: int,
) -> dict[str, Any]:
    per_arm = {
        arm: [group_aucs(outcomes, scores, groups) for scores in arm_scores]
        for arm, arm_scores in arms.items()
        if arm_scores is not None
    }
    classes = pd.DataFrame({"group": groups, "outcome": outcomes}).groupby("group")["outcome"].agg(["min", "max"])
    graded_users = classes.index[(classes["min"] == 0) & (classes["max"] == 1)]
    grade: dict[str, Any] = {
        "rows": len(outcomes),
        "positives": int(outcomes.sum()),
        "users": len(graded_users),
        "teams": int(group_teams.loc[graded_users].nunique()),
    }
    reads: dict[str, dict[str, list[float | None]]] = {}
    for arm in (EXPERIMENT_ARM, BASELINE_ARM, REFERENCE_ARM):
        if arm not in per_arm:
            grade[arm] = None
            continue
        summaries = [summarize_groups(per_group) for per_group in per_arm[arm]]
        reads[arm] = {"macro": [s.macro for s in summaries], "pooled": [s.auc for s in summaries]}
        grade[arm] = reads[arm]
    for name, other in COMPARISONS:
        if other not in per_arm:
            grade[name] = None
            continue
        grade[name] = {
            **{read: _delta_summary(reads[EXPERIMENT_ARM][read], reads[other][read]) for read in READS},
            "macro_team_interval": team_interval(per_arm[EXPERIMENT_ARM], per_arm[other], group_teams, draws=draws),
        }
    return grade


def pair_vs_baseline_block(
    table: ExampleTable,
    heads: Sequence[str],
    *,
    baseline: str | None,
    reference: str | None,
    seeds: Sequence[int],
    experiment_scores: Sequence[np.ndarray],
    baseline_scores: Sequence[np.ndarray] | None = None,
    reference_scores: Sequence[np.ndarray] | None = None,
    draws: int = BOOTSTRAP_DRAWS,
) -> dict[str, Any]:
    """The `vs_baseline` block of a pair experiment, per head, on the same holdout pairs.

    `table` holds one row per pair with labels in `heads` order. Every score array holds a row per
    pair and a column per head, one array per seed. The reference scores are its report scores
    broadcast to every pair of the report. An arm that is None (no pair baseline, or no reference)
    leaves its reads and its deltas None.
    """
    train_rows = table.network_train_rows()
    graded: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(heads):
        rows = table.head_rows(index, holdout=True)
        frame = table.rows.iloc[rows].reset_index(drop=True)
        outcomes = table.labels[rows, index].astype(int)
        groups = frame.groupby(_GROUP_COLUMNS, sort=False).ngroup().to_numpy()
        group_teams = pd.Series(frame["report_team_id"].to_numpy(), index=groups).groupby(level=0).first()
        arm_scores = {
            EXPERIMENT_ARM: [scores[rows, index] for scores in experiment_scores],
            BASELINE_ARM: [scores[rows, index] for scores in baseline_scores] if baseline_scores is not None else None,
            REFERENCE_ARM: (
                [scores[rows, index] for scores in reference_scores] if reference_scores is not None else None
            ),
        }
        slices = pair_slices(frame)
        graded[name] = {
            "train_rows": int((~np.isnan(table.labels[train_rows, index])).sum()),
            "holdout_rows": len(rows),
            "holdout_positives": int(outcomes.sum()),
            "holdout_users": len(np.unique(groups)),
            "scopes": {
                scope: {
                    slice_name: _slice_grade(
                        outcomes[scope_mask & slice_mask],
                        groups[scope_mask & slice_mask],
                        group_teams,
                        {
                            arm: [scores[scope_mask & slice_mask] for scores in per_seed]
                            if per_seed is not None
                            else None
                            for arm, per_seed in arm_scores.items()
                        },
                        draws,
                    )
                    for slice_name, slice_mask in slices.items()
                }
                for scope, scope_mask in pair_scopes(frame).items()
            },
        }
    return {"grain": PAIR_GRAIN, "baseline": baseline, "reference": reference, "seeds": list(seeds), "heads": graded}
