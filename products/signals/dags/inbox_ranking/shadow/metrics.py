"""Shadow evaluation: the model's order against the order the inbox served.

Every read the ranking model has today is offline. The holdout grades the recipe, the unseen read
grades the model on reports it never saw, and neither one compares the model against the list
people actually get, which is still a fixed sort. This module builds that comparison from data
already flowing: an `Inbox reports impressed` event carries a set of rows at the ranks the list
served them, the unseen scores say how the model would have ordered them, and the opens and
actions that follow the impression say which rows were worth the top.

Three orders are graded on each list, on exactly the same rows:

- `model`, descending score of the head whose outcome is being graded, with unscored rows last;
- `heuristic`, every row at the rank the list served, pooling all served sorts;
- `random`, seeded permutations, the chance line a gap has to clear.

Each set of three is graded under two scopes, because a day's lists are mostly part-scored:

- `all_rows`, every reconstructed row, with the unscored ones last in the model order;
- `scored_rows`, the same lists narrowed to the rows the model had a score for.

A list with no scored row at all is graded under neither. Every score there ties at minus
infinity, the model order collapses onto the served order, and the two lines draw level for free.

Pure functions over frames; `shadow/dag.py` owns the ClickHouse, S3 and telemetry plumbing.

**Position bias is not corrected for.** Every recorded open happened under the served order, so a
report the heuristic put first had more chance to be opened than one it put twentieth, whatever
either order thinks of it. That flatters the heuristic line and no re-ranking of logged clicks can
remove it. `positive_served_rank_mean` reports how concentrated the outcomes were at the top of
the served list, so the size of the effect is visible next to the numbers it distorts.

**Only complete reconstructed lists are graded.** Events are unioned by absolute rank inside a
five-second UTC bucket for the same viewer, session, scope and normalized tab. State-section
tabs normalize to `reports` so merged sections meet. The maximum list_size must equal the row
count, ranks must be contiguous, and conflicting rank assignments are excluded. Pagination
inside the bucket extends the list; later incomplete pages are excluded. Without a render ID,
the bucket can split a render or combine nearby visits, so this is a conservative approximation.
Repeat visits in different buckets stay separate. Under `all_rows`, unscored reports keep their
outcomes and rank last in the model order, tied on served rank; a group with no available scores
is not graded.

**A part-scored list handicaps the model order, and `scored_rows` is how that is read off.** An
unscored row sinks to the bottom of the model order while the served order keeps it where it was,
so an outcome that lands on one costs the model line and costs the heuristic line nothing. That is
a coverage effect, not a ranking one. The `scored_rows` scope removes it by grading both orders on
the rows the model could actually order, at the price of a shorter list under the NDCG cutoffs.
`scored_list_share`, `score_pending_share` and `never_scored_share` say how much of the day each
scope rests on.

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

# Which rows of a list a grade is computed over. Both require at least one scored row.
ALL_ROWS_SCOPE = "all_rows"
SCORED_ROWS_SCOPE = "scored_rows"
GRADING_SCOPES: tuple[str, ...] = (ALL_ROWS_SCOPE, SCORED_ROWS_SCOPE)

NDCG_CUTOFFS: tuple[int, ...] = (5, 10)

# Seeded and fixed, so re-grading the same day reports the same chance line.
RANDOM_PERMUTATIONS = 25
RANDOM_SEED = 0

# How long after seeing a list an engagement still counts as that list's. Opens land within
# minutes of the impression; a window of hours would credit a list for a report the person came
# back to from a link or a notification.
ATTRIBUTION_WINDOW = datetime.timedelta(minutes=30)

RENDER_WINDOW = "5s"
SECTION_TABS = ("monitoring", "needs-decision", "resolved", "dismissed", "not-actionable")

# A list of one is ranked identically by every order, so it separates nothing and only adds weight
# to the average.
MIN_LIST_SIZE = 2

SCORE_JOIN_COLUMNS = ("report_id", "snapshot_date", "model_name", "model_version", "model_role", "head", "score")


def outcome_column(outcome: str) -> str:
    return f"outcome_{outcome}"


@frozen
class RankingGrade:
    """One model, one outcome, one order, one grading scope, over the lists that had that outcome.

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
    # Which rows of each list the three orders were graded over; one of `GRADING_SCOPES`.
    grading_scope: str
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
    # Share of served lists holding at least one scored row: the lists either scope can grade.
    # `full_list_coverage` is the stricter share of those that were scored right through.
    scored_list_share: float | None
    # The two halves of what `score_coverage` is missing, so a thin read says which cause it has.
    # Pending rows had a score written after the list was served, which is the birth-day residual
    # the daily job cannot avoid. Never-scored rows had none anywhere in the lookback window: a
    # report the pool never held. The three shares sum to 1.
    score_pending_share: float | None
    never_scored_share: float | None
    # Whether any scored row the group held came from `load_scores` reading candidate rows in
    # place of a missing champion. Group-level like the shares above, so it can warn on a line
    # whose own graded rows are all real champion scores; it never stays False on one that is not.
    champion_is_fallback: bool

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
            "scored_list_share": self.scored_list_share,
            "score_pending_share": self.score_pending_share,
            "never_scored_share": self.never_scored_share,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "model_name": self.model_name,
            "model_role": self.model_role,
            "model_versions": self.model_versions,
            "outcome": self.outcome,
            "ranking_order": self.ranking_order,
            "grading_scope": self.grading_scope,
            "champion_is_fallback": self.champion_is_fallback,
            **self.metrics(),
        }


@frozen
class ServedList:
    """One impression's rows, as three aligned arrays: was it engaged with, what the model scored
    it, and where the list put it."""

    relevance: np.ndarray
    score: np.ndarray
    served_rank: np.ndarray


def deduplicate_lists(impressions: pd.DataFrame) -> pd.DataFrame:
    """Reassemble complete render windows after per-event outcome attribution.

    Attribute first so a later incomplete impression cannot credit an earlier complete list.
    Duplicate rows retain any outcome attributed to their latest event in the render window.
    """
    if impressions.empty:
        return impressions
    rows = impressions.assign(
        render_window=impressions["impressed_at"].dt.floor(RENDER_WINDOW),
        tab=impressions["tab"].replace(dict.fromkeys(SECTION_TABS, "reports")),
    )
    complete: list[pd.DataFrame] = []
    for _, render in rows.groupby(["distinct_id", "session_id", "scope", "tab", "render_window"], sort=True):
        size = render["list_size"].max()
        if pd.isna(size) or size < 1 or not render["session_id"].iloc[0]:
            continue
        if (render.groupby("served_rank")["report_id"].nunique() > 1).any():
            continue
        ranked = render.sort_values(["impressed_at", "impression_id"]).drop_duplicates("served_rank")
        if (
            len(ranked) != size
            or ranked["report_id"].nunique() != size
            or set(ranked["served_rank"]) != set(range(1, int(size) + 1))
        ):
            continue
        ranked = ranked.assign(
            **{
                column: ranked["served_rank"].map(render.groupby("served_rank")[column].max())
                for outcome in OUTCOMES
                if (column := outcome_column(outcome)) in render
            }
        )
        complete.append(
            ranked.assign(impression_id=render["impression_id"].min(), list_size=size).drop(columns="render_window")
        )
    return pd.concat(complete, ignore_index=True) if complete else impressions.head(0)


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

    Unscored reports retain a null score and all their outcomes for each model group. The model
    orders them last. A group with no score available for any served row produces no grades.

    `score_pending` splits the unscored rows in two: True when a score for the row exists in the
    lookback window but was written after the list was served, which is the birth-day residual the
    daily job cannot avoid, and False when the window holds no score for the row at all.
    """
    key = ["impression_id", "report_id", "model_name", "model_role", "head"]
    if lists.empty or scores.empty:
        return lists.head(0).merge(scores.head(0), on="report_id", how="inner").assign(score_pending=False)
    joined = lists.merge(scores, on="report_id", how="inner")
    available = joined.loc[joined["available_at"] <= joined["impressed_at"]]
    matched = available.sort_values(["snapshot_date", "available_at", "model_version"]).drop_duplicates(
        subset=key, keep="last"
    )
    groups = scores[["model_name", "model_role", "head"]].drop_duplicates()
    known = joined[key].drop_duplicates().assign(had_score=True)
    side = known.merge(
        matched.drop(columns=lists.columns.difference(["impression_id", "report_id"])), on=key, how="left"
    )
    rows = lists.merge(groups, how="cross").merge(side, on=key, how="left")
    return rows.assign(score_pending=rows.pop("had_score").notna() & rows["score"].isna())


def score_coverage(served_rows: int, joined: pd.DataFrame) -> float | None:
    """Share of served rows a model score was available for. The number the whole read rests on:
    before this asset it was zero, because no scoring moment was ever paired with a served list.

    Over the whole join it is the run's coverage; over one grade's rows it is that grade's. They
    part whenever a head or a family scored fewer of the days the lists came from, so the run
    figure alone would let a thin grade read as a well-covered one.
    """
    if not served_rows:
        return None
    covered = joined.loc[joined["score"].notna()].drop_duplicates(subset=["impression_id", "report_id"])
    return float(len(covered) / served_rows)


def served_lists(rows: pd.DataFrame, outcome: str, *, scope: str = ALL_ROWS_SCOPE) -> list[ServedList]:
    """The gradeable lists of one (model, head) group, under one grading scope.

    A list with no outcome is dropped: NDCG has no ideal ranking to normalize against and the
    reciprocal rank has no hit, so every order would score the same nothing. A list with no scored
    row is dropped under both scopes, and `scored_rows` keeps only the rows the group scored; the
    module docstring says why.

    Rows are put in served order first. Neither deterministic order cares which arrangement they
    arrive in, because both sort on `served_rank`, but the seeded permutations are applied to the
    array as it stands. The impression query has no `ORDER BY`, so without this a re-run of the
    partition could hand the same rows over differently and publish a different chance line.
    """
    column = outcome_column(outcome)
    lists: list[ServedList] = []
    for _, group in rows.groupby("impression_id", sort=True):
        scored = group.loc[group["score"].notna()]
        if scored.empty:
            continue
        ordered = (scored if scope == SCORED_ROWS_SCOPE else group).sort_values(["served_rank", "report_id"])
        relevance = ordered[column].to_numpy(dtype=float)
        if len(ordered) < MIN_LIST_SIZE or relevance.sum() == 0:
            continue
        lists.append(
            ServedList(
                relevance=relevance,
                score=ordered["score"].fillna(-np.inf).to_numpy(dtype=float),
                served_rank=ordered["served_rank"].to_numpy(dtype=float),
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
    return float(rows.loc[rows["score"].notna(), outcome_column(outcome)].sum() / served_positives)


def _list_coverages(rows: pd.DataFrame, served_per_list: pd.Series) -> dict[str, float | None]:
    """How much of each served list this group scored: the share it can grade at all, and the
    stricter share it scored right through."""
    per_list = (
        rows.loc[rows["score"].notna()].groupby("impression_id").size().reindex(served_per_list.index, fill_value=0)
    )
    if per_list.empty:
        return {"scored_list_share": None, "full_list_coverage": None}
    return {
        "scored_list_share": float((per_list > 0).mean()),
        "full_list_coverage": float((per_list == served_per_list.reindex(per_list.index)).mean()),
    }


def _unscored_shares(rows: pd.DataFrame, served_rows: int) -> dict[str, float | None]:
    """The two reasons a served row carries no score, each as a share of the served rows.

    With `score_coverage` these three sum to 1, so a thin read says whether it is waiting for the
    next training run or looking at reports the pool never held.
    """
    if not served_rows:
        return {"score_pending_share": None, "never_scored_share": None}
    unscored = rows.loc[rows["score"].isna()].drop_duplicates(subset=["impression_id", "report_id"])
    pending = int(unscored["score_pending"].sum())
    return {
        "score_pending_share": float(pending / served_rows),
        "never_scored_share": float((len(unscored) - pending) / served_rows),
    }


def grade_lists(joined: pd.DataFrame, *, served: pd.DataFrame) -> list[RankingGrade]:
    """Three grades per (model, outcome, grading scope): the model's order, the served order, and
    chance.

    Grouping is by model family and role rather than version for the reason `RankingGrade` gives:
    one day's lists are ranked by whichever version scored each report at its birth.

    `model_role` is the snapshot role, not the current serving policy. Missing champion partitions
    use candidate scores as a fallback in `load_scores`, and `champion_is_fallback` says when the
    group holds one. Coverage reports actual non-null scores per group, and is a property of the
    group rather than of the scope, so the same figures ride on both scopes of a group.
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
        scored = rows["score"].notna()
        if not scored.any():
            continue
        coverage: dict[str, Any] = {
            "model_name": str(model_name),
            "model_role": str(model_role),
            "model_versions": int(rows["model_version"].nunique()),
            "outcome": str(head),
            "score_coverage": score_coverage(served_rows, rows),
            "positive_coverage": _positive_coverage(rows, str(head), served_positives[str(head)]),
            "champion_is_fallback": bool(rows.loc[scored, "score_is_fallback"].any()),
            **_list_coverages(rows, served_per_list),
            **_unscored_shares(rows, served_rows),
        }
        for scope in GRADING_SCOPES:
            lists = served_lists(rows, str(head), scope=scope)
            if not lists:
                continue
            shared: dict[str, Any] = {
                **coverage,
                "grading_scope": scope,
                "lists": len(lists),
                "reports": sum(len(entry.relevance) for entry in lists),
                "mean_list_size": float(np.mean([len(entry.relevance) for entry in lists])),
                "positive_served_rank_mean": _positive_served_rank_mean(lists),
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
