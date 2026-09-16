"""Shadow evaluation: the model's order against the order the inbox served.

Every read the ranking model has today is offline. The holdout grades the recipe, the unseen read
grades the model on reports it never saw, and neither one compares the model against the list
people actually get, which is still a fixed sort. This module builds that comparison from data
already flowing: one `Inbox reports impressed` event is one ranked list, the unseen scores say how
the model would have ordered it, and the opens and actions that follow the impression say which
rows were worth the top of the list.

Three orders are graded on each list, on exactly the same rows:

- `model`, descending score of the head whose outcome is being graded;
- `heuristic`, the rank the list served, which is what the person saw, minus any row no score
  existed for;
- `random`, seeded permutations, the chance line a gap has to clear.

Pure functions over frames; `shadow/dag.py` owns the ClickHouse, S3 and telemetry plumbing.

**Position bias is not corrected for.** Every recorded open happened under the served order, so a
report the heuristic put first had more chance to be opened than one it put twentieth, whatever
either order thinks of it. That flatters the heuristic line and no re-ranking of logged clicks can
remove it. `positive_served_rank_mean` reports how concentrated the outcomes were at the top of
the served list, so the size of the effect is visible next to the numbers it distorts.

**The graded outcome is a list-scoped proxy for the head it is named after, not that head's own
label.** Relevance here is "the person who saw this list engaged with this row inside the
attribution window", which is what an order can be held responsible for. The `open` head predicts
"anyone opened this report within three days" and `action` the same over seven, both counted per
report rather than per viewer. The scores being ranked are the head's, so a head is graded against
the outcome it was fit toward, but a shadow NDCG and an unseen AUC of the same name answer
different questions and are not one number.
"""

import datetime
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from posthog.dataclasses import frozen

# The outcomes graded, each named after the head whose scores order it. Not that head's label: the
# module docstring has the horizon and grain the proxy does not carry.
OPEN_OUTCOME = "open"
ACTION_OUTCOME = "action"
OUTCOMES: tuple[str, ...] = (OPEN_OUTCOME, ACTION_OUTCOME)

MODEL_ORDER = "model"
HEURISTIC_ORDER = "heuristic"
RANDOM_ORDER = "random"

NDCG_CUTOFFS: tuple[int, ...] = (5, 10)

# Seeded and fixed, so re-grading the same day reports the same chance line.
RANDOM_PERMUTATIONS = 25
RANDOM_SEED = 0

# How long after seeing a list an engagement still counts as that list's. Opens land within
# minutes of the impression; a window of hours would credit a list for a report the person came
# back to from a link or a notification.
ATTRIBUTION_WINDOW = datetime.timedelta(minutes=30)

# When a dt=D score becomes something a sweep could have served: the training job is scheduled at
# 06:00 UTC the next morning, so a score is counterfactually available from D+1 06:00 and not
# before. Comparing on snapshot day alone would let a list served at 03:00 use a model that had
# not been fit yet.
SCORE_AVAILABLE_AFTER = datetime.timedelta(days=1, hours=6)

# A list of one is ranked identically by every order, so it separates nothing and only adds weight
# to the average.
MIN_LIST_SIZE = 2

SCORE_JOIN_COLUMNS = ("report_id", "snapshot_date", "model_name", "model_version", "model_role", "head", "score")


def outcome_column(outcome: str) -> str:
    return f"outcome_{outcome}"


@frozen
class RankingGrade:
    """One model, one outcome, one order, over the lists that had that outcome.

    `model_versions` counts the distinct model versions in the group: a report is scored on the day
    it is born, so a day of lists is ranked by whichever version was current when each of its
    reports appeared. That is the serving situation, not a mixing bug — the champion pointer a
    sweep would load moves the same way.
    """

    model_name: str
    model_role: str
    model_versions: int
    outcome: str
    ranking_order: str
    # Lists that had at least one of this outcome and at least MIN_LIST_SIZE scored rows. A list
    # with no outcome has no ideal ranking to score against, so it is not graded.
    lists: int
    reports: int
    mean_list_size: float
    ndcg_5: float | None
    ndcg_10: float | None
    mrr: float | None
    # Spread across the seeded draws, so the random line carries its own noise band. None for the
    # two deterministic orders.
    ndcg_5_std: float | None
    ndcg_10_std: float | None
    mrr_std: float | None
    # Mean served rank of the rows that drew the outcome: how much of the outcome the top of the
    # served list already collected, which is the size of the position bias in these numbers.
    positive_served_rank_mean: float | None
    # This group's own coverage, not the run's. A head is only scored on a partition where the
    # training job found it readable, and a family is skipped on a partition it has no metadata
    # for, so one grade can rest on far fewer of the served rows than another one of the same day.
    score_coverage: float | None
    # The same share over the served rows that drew this outcome. The join drops unscored rows,
    # and those are the reports born on the day they were impressed, which is where an open lands
    # most often. Below 1 these lists are conditioned on the outcome falling on an older report.
    positive_coverage: float | None
    # Share of this group's lists that kept every row the person saw. Below 1 the rest were graded
    # with their unscored rows removed, so the served ranks close up and the NDCG cutoffs bite on
    # a shorter list than the one that was rendered.
    full_list_coverage: float | None

    def metrics(self) -> dict[str, int | float | None]:
        return {
            "lists": self.lists,
            "reports": self.reports,
            "mean_list_size": self.mean_list_size,
            "ndcg_5": self.ndcg_5,
            "ndcg_10": self.ndcg_10,
            "mrr": self.mrr,
            "ndcg_5_std": self.ndcg_5_std,
            "ndcg_10_std": self.ndcg_10_std,
            "mrr_std": self.mrr_std,
            "positive_served_rank_mean": self.positive_served_rank_mean,
            "score_coverage": self.score_coverage,
            "positive_coverage": self.positive_coverage,
            "full_list_coverage": self.full_list_coverage,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "model_name": self.model_name,
            "model_role": self.model_role,
            "model_versions": self.model_versions,
            "outcome": self.outcome,
            "ranking_order": self.ranking_order,
            **self.metrics(),
        }


@frozen
class ServedList:
    """One impression's rows, as three aligned arrays: was it engaged with, what the model scored
    it, and where the list put it."""

    relevance: np.ndarray
    score: np.ndarray
    served_rank: np.ndarray


def score_available_at(snapshot_date: pd.Series) -> pd.Series:
    """The instant each scoring day's scores could first have been served."""
    return pd.to_datetime(snapshot_date, utc=True) + SCORE_AVAILABLE_AFTER


def _first_render_of_each_visit(per_list: pd.DataFrame) -> set[str]:
    """The earliest render of each visit. A render repeats the last kept one when the same list
    came back inside an attribution window of it."""
    keep: set[str] = set()
    last_kept: dict[tuple[Any, ...], pd.Timestamp] = {}
    for impression_id, render in per_list.sort_values("impressed_at").iterrows():
        key = (render["distinct_id"], render["tab"], render["scope"], render["reports"], render["ranks"])
        previous = last_kept.get(key)
        if previous is not None and render["impressed_at"] - previous < ATTRIBUTION_WINDOW:
            continue
        last_kept[key] = render["impressed_at"]
        keep.add(str(impression_id))
    return keep


def deduplicate_lists(impressions: pd.DataFrame) -> pd.DataFrame:
    """One row per (list, report), collapsing repeats of the same list into their first render.

    Coming back to a query the person already ran is a fresh ranking context to the client, so
    toggling a filter back and forth re-sends the same ranking within a minute. Left alone, one
    person's toggling outweighs everyone else's reading. Two renders are the same list when the
    same person saw the same reports at the same ranks in the same place.

    The attribution window is what makes a repeat a repeat, and it is why this is not a plain
    drop-duplicates over the day. Renders closer together than that window compete for the same
    engagements, so they are one viewing. A person who comes back hours later and opens something
    has made a second observation, and folding it into the morning's render loses the open
    entirely: the engagement falls outside that render's window, and the render is then dropped
    for having no outcome at all.
    """
    if impressions.empty:
        return impressions
    per_list = (
        impressions.sort_values(["impression_id", "served_rank"])
        .groupby("impression_id", sort=False)
        .agg(
            distinct_id=("distinct_id", "first"),
            tab=("tab", "first"),
            scope=("scope", "first"),
            impressed_at=("impressed_at", "min"),
            reports=("report_id", tuple),
            ranks=("served_rank", tuple),
        )
    )
    return impressions.loc[impressions["impression_id"].isin(_first_render_of_each_visit(per_list))]


def with_outcomes(impressions: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """`impressions` with one boolean column per outcome: did this person engage with this report
    within the attribution window of seeing it in this list."""
    engaged = impressions.copy()
    for outcome in OUTCOMES:
        engaged[outcome_column(outcome)] = False
    if impressions.empty or outcomes.empty:
        return engaged
    pairs = impressions[["impression_id", "distinct_id", "report_id", "impressed_at"]].merge(
        outcomes, on=["distinct_id", "report_id"], how="inner"
    )
    within = (pairs["timestamp"] >= pairs["impressed_at"]) & (
        pairs["timestamp"] < pairs["impressed_at"] + ATTRIBUTION_WINDOW
    )
    # One engagement belongs to one list: the last one the person saw the report in before they
    # engaged. A filter or sort change re-impresses the same rows at new ranks, so an open inside
    # the window of several renders would otherwise mark every one of them relevant. The
    # `impression_id` tie-break keeps a re-run of the partition on the same choice.
    attributed = (
        pairs.loc[within]
        .sort_values(["impressed_at", "impression_id"])
        .drop_duplicates(subset=["distinct_id", "report_id", "timestamp", "outcome"], keep="last")
    )
    keys = list(zip(engaged["impression_id"], engaged["report_id"], strict=True))
    for outcome in OUTCOMES:
        hits = set(
            map(tuple, attributed.loc[attributed["outcome"] == outcome, ["impression_id", "report_id"]].to_numpy())
        )
        engaged[outcome_column(outcome)] = [key in hits for key in keys]
    return engaged


def join_scores(lists: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    """One row per (list, report, model, head), carrying the newest score that existed when the
    list was served.

    A report is scored on the day it is born, so a list served on its birth day joins nothing: the
    daily job that would have scored it has not run yet. Those rows are the residual the coverage
    number reports, and they cannot be recovered without scoring at birth.
    """
    if lists.empty or scores.empty:
        return lists.head(0).merge(scores.head(0), on="report_id", how="inner")
    joined = lists.merge(scores, on="report_id", how="inner")
    joined = joined.loc[joined["available_at"] <= joined["impressed_at"]]
    return joined.sort_values("snapshot_date").drop_duplicates(
        subset=["impression_id", "report_id", "model_name", "model_role", "head"], keep="last"
    )


def score_coverage(served_rows: int, joined: pd.DataFrame) -> float | None:
    """Share of served rows a model score was available for. The number the whole read rests on:
    before this asset it was zero, because no scoring moment was ever paired with a served list.

    Over the whole join it is the run's coverage; over one grade's rows it is that grade's. They
    part whenever a head or a family scored fewer of the days the lists came from, so the run
    figure alone would let a thin grade read as a well-covered one.
    """
    if not served_rows:
        return None
    covered = joined.drop_duplicates(subset=["impression_id", "report_id"])
    return float(len(covered) / served_rows)


def served_lists(rows: pd.DataFrame, outcome: str) -> list[ServedList]:
    """The gradeable lists of one (model, head) group.

    A list with no outcome is dropped: NDCG has no ideal ranking to normalize against and the
    reciprocal rank has no hit, so every order would score the same nothing.
    """
    column = outcome_column(outcome)
    lists: list[ServedList] = []
    for _, group in rows.groupby("impression_id", sort=True):
        relevance = group[column].to_numpy(dtype=float)
        if len(group) < MIN_LIST_SIZE or relevance.sum() == 0:
            continue
        lists.append(
            ServedList(
                relevance=relevance,
                score=group["score"].to_numpy(dtype=float),
                served_rank=group["served_rank"].to_numpy(dtype=float),
            )
        )
    return lists


def _dcg(relevance: np.ndarray, k: int) -> float:
    top = relevance[:k]
    return float((top / np.log2(np.arange(2, len(top) + 2))).sum())


def ndcg_at_k(relevance_in_order: np.ndarray, k: int) -> float:
    """Binary-relevance NDCG at `k`, normalized by the best this list could have done."""
    ideal = _dcg(np.sort(relevance_in_order)[::-1], k)
    return _dcg(relevance_in_order, k) / ideal if ideal else 0.0


def reciprocal_rank(relevance_in_order: np.ndarray) -> float:
    hits = np.flatnonzero(relevance_in_order)
    return float(1.0 / (hits[0] + 1)) if len(hits) else 0.0


def _order_metrics(ordered: Sequence[np.ndarray]) -> dict[str, float]:
    """Mean of each metric over the lists, each already in the order being graded."""
    return {
        **{f"ndcg_{k}": float(np.mean([ndcg_at_k(relevance, k) for relevance in ordered])) for k in NDCG_CUTOFFS},
        "mrr": float(np.mean([reciprocal_rank(relevance) for relevance in ordered])),
    }


def _model_ordered(lists: Sequence[ServedList]) -> list[np.ndarray]:
    # Ties break on the served rank, so a model that scores a whole list alike neither gains nor
    # loses against the heuristic on it.
    return [entry.relevance[np.lexsort((entry.served_rank, -entry.score))] for entry in lists]


def _heuristic_ordered(lists: Sequence[ServedList]) -> list[np.ndarray]:
    return [entry.relevance[np.argsort(entry.served_rank, kind="stable")] for entry in lists]


def _random_draws(lists: Sequence[ServedList]) -> Iterator[list[np.ndarray]]:
    rng = np.random.default_rng(RANDOM_SEED)
    for _ in range(RANDOM_PERMUTATIONS):
        yield [rng.permutation(entry.relevance) for entry in lists]


def _random_metrics(lists: Sequence[ServedList]) -> dict[str, float | None]:
    """Mean and spread of each metric across the seeded draws."""
    draws = [_order_metrics(ordered) for ordered in _random_draws(lists)]
    metrics: dict[str, float | None] = {}
    for name in draws[0]:
        values = [draw[name] for draw in draws]
        metrics[name] = float(np.mean(values))
        metrics[f"{name}_std"] = float(np.std(values))
    return metrics


def _positive_served_rank_mean(lists: Sequence[ServedList]) -> float | None:
    ranks = np.concatenate([entry.served_rank[entry.relevance > 0] for entry in lists])
    return float(ranks.mean()) if len(ranks) else None


def _positive_coverage(rows: pd.DataFrame, outcome: str, served_positives: int) -> float | None:
    """Share of the served rows that drew `outcome` which this group had a score for."""
    if not served_positives:
        return None
    return float(rows[outcome_column(outcome)].sum() / served_positives)


def _full_list_coverage(rows: pd.DataFrame, served_per_list: pd.Series) -> float | None:
    """Share of this group's lists that the join left whole."""
    per_list = rows.groupby("impression_id").size()
    if per_list.empty:
        return None
    return float((per_list == served_per_list.reindex(per_list.index)).mean())


def grade_lists(joined: pd.DataFrame, *, served: pd.DataFrame) -> list[RankingGrade]:
    """Three grades per (model, outcome): the model's order, the served order, and chance.

    Grouping is by model family and role rather than version for the reason `RankingGrade` gives:
    one day's lists are ranked by whichever version scored each report at its birth.

    `served` is the pre-join frame, and it is here to be a denominator. The join keeps only the
    rows a score existed for, so the graded lists are a subset of the rendered ones in two ways
    the ranking metrics cannot show: an outcome on an unscored row leaves the sample entirely, and
    a surviving list loses the rows above its positives. `positive_coverage` and
    `full_list_coverage` report both, the way `positive_served_rank_mean` reports position bias.
    """
    grades: list[RankingGrade] = []
    if joined.empty:
        return grades
    served_rows = len(served)
    served_per_list = served.groupby("impression_id").size()
    served_positives = {outcome: int(served[outcome_column(outcome)].sum()) for outcome in OUTCOMES}
    for (model_name, model_role, head), rows in joined.groupby(["model_name", "model_role", "head"], sort=True):
        if head not in OUTCOMES:
            continue
        lists = served_lists(rows, str(head))
        if not lists:
            continue
        shared: dict[str, Any] = {
            "model_name": str(model_name),
            "model_role": str(model_role),
            "model_versions": int(rows["model_version"].nunique()),
            "outcome": str(head),
            "lists": len(lists),
            "reports": sum(len(entry.relevance) for entry in lists),
            "mean_list_size": float(np.mean([len(entry.relevance) for entry in lists])),
            "positive_served_rank_mean": _positive_served_rank_mean(lists),
            "score_coverage": score_coverage(served_rows, rows),
            "positive_coverage": _positive_coverage(rows, str(head), served_positives[str(head)]),
            "full_list_coverage": _full_list_coverage(rows, served_per_list),
        }
        grades.extend(
            _grade(shared, ranking_order=order, metrics=metrics)
            for order, metrics in (
                (MODEL_ORDER, _order_metrics(_model_ordered(lists))),
                (HEURISTIC_ORDER, _order_metrics(_heuristic_ordered(lists))),
                (RANDOM_ORDER, _random_metrics(lists)),
            )
        )
    return grades


def _grade(shared: Mapping[str, Any], *, ranking_order: str, metrics: Mapping[str, float | None]) -> RankingGrade:
    return RankingGrade(
        ranking_order=ranking_order,
        ndcg_5=metrics.get("ndcg_5"),
        ndcg_10=metrics.get("ndcg_10"),
        mrr=metrics.get("mrr"),
        ndcg_5_std=metrics.get("ndcg_5_std"),
        ndcg_10_std=metrics.get("ndcg_10_std"),
        mrr_std=metrics.get("mrr_std"),
        **shared,
    )
